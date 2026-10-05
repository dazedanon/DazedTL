"""Transport-independent acceptance, submission journaling, and safe resume."""

from dazedtl.storage import write_json
from .files import read_json
from .results import Results
from .refusals import POLICY as REFUSAL_POLICY, MESSAGE as REFUSAL_MESSAGE, clarified, clarifiable, refused


class Runner:
    def __init__(self, store, identity, provider, validate_current, checkpoint=lambda: None):
        self.store = store
        self.job, self.plan = store.load(identity)
        self.provider = provider
        self.validate_current = validate_current
        self.checkpoint = checkpoint
        self.results = Results(self.plan["source"])
        self.folder = store.folder(identity)
        self.requests = {row["id"]: row for row in self.plan["requests"]}

    def save(self, status=None, message=None):
        if status is not None:
            self.job["status"] = status
        if message is not None:
            self.job["message"] = message
        self.store.save(self.job)

    def response_path(self, identity, *, original=False):
        from .files import digest
        suffix = "-clarified" if not original and identity in self.job.get("refusal_retries", {}) else ""
        return self.folder / "responses" / (digest(identity) + suffix + ".json")

    def accept(self, identity, response):
        request = self.requests[identity]
        write_json(self.response_path(identity), response)
        self.record_usage(identity, response)
        try:
            if refused(response, request["sources"].values()):
                raise ValueError(REFUSAL_MESSAGE)
            self.results.accept(request, response["text"], {"run_id": self.job["id"],
                                "mode": self.plan["configuration"]["mode"], "model": self.plan["configuration"]["model"]})
            self.job["states"][identity] = {"state": "accepted", "message": ""}
        except ValueError as exc:
            self.job["states"][identity] = {"state": "failed", "message": str(exc)}
        self.save()
        self.checkpoint()

    def record_usage(self, identity, response):
        if identity in self.job.get("refusal_retries", {}):
            original = read_json(self.response_path(identity, original=True))
            response = {key: (response.get(key, 0) if type(response.get(key, 0)) is int else 0) +
                        (original.get(key, 0) if type(original.get(key, 0)) is int else 0)
                        for key in set(response) | set(original) if key.endswith("tokens")}
        def count(key):
            value = response.get(key, 0)
            return value if type(value) is int and value >= 0 else 0
        cached, created = count("cache_read_input_tokens"), count("cache_creation_input_tokens")
        self.job.setdefault("request_usage", {})[identity] = {
            "input_tokens": max(0, count("prompt_tokens") - cached - created), "output_tokens": count("completion_tokens"),
            "cache_read_input_tokens": cached, "cache_creation_input_tokens": created, "thinking_tokens": count("thinking_tokens")}
        self.job["usage"] = {key: sum(row[key] for row in self.job["request_usage"].values())
                             for key in self.job["request_usage"][identity]}

    def recover(self):
        for identity, request in self.requests.items():
            if self.response_path(identity).exists():
                self.record_usage(identity, read_json(self.response_path(identity)))
            if self.results.get(request):
                self.job["states"][identity] = {"state": "accepted", "message": ""}
            elif self.response_path(identity).exists():
                self.accept(identity, read_json(self.response_path(identity)))
            elif self.job["states"][identity]["state"] == "sending":
                self.job["states"][identity] = {"state": "uncertain", "message": "The connection ended without a saved response. Check provider usage before explicitly retrying."}
        if self.plan['configuration']['mode'] == 'batch':
            self.record_batch_usage()
        self.save()

    def record_batch_usage(self):
        receipts = [batch['usage'] for batch in self.job['batches'] if 'usage' in batch]
        if receipts:
            self.job['usage'] = {key: sum(row.get(key, 0) for row in receipts) for key in set().union(*receipts)}

    def live(self):
        for identity, request in self.requests.items():
            state = self.job["states"][identity]["state"]
            if state != "pending":
                continue
            if self.store.stopped(self.job["id"]):
                self.save("stopped", "Stopped at a saved request boundary.")
                return
            self.validate_current()
            self.job["states"][identity] = {"state": "sending", "message": "Awaiting provider response."}
            self.save("running", "Translating " + identity)
            try:
                response = self.provider.live(request["params"])
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                certain = type(status) is int and 400 <= status < 500
                self.job["states"][identity] = {"state": "failed" if certain else "uncertain",
                    "message": "Provider rejected the request (HTTP " + str(status) + ")." if certain else
                               "The request outcome is uncertain. It will not be sent again automatically."}
                self.save("needs_attention" if certain else "uncertain", self.job["states"][identity]["message"])
                return
            self.accept(identity, response)
            if (clarifiable(response, request["sources"].values())
                    and self.plan["configuration"].get("refusalRetry") == REFUSAL_POLICY
                    and identity not in self.job.get("refusal_retries", {})):
                if self.store.stopped(self.job["id"]):
                    self.save("stopped", "Stopped before the clarification retry.")
                    return
                self.validate_current()
                params = clarified(request["params"])
                # Journal the exact second payload before sending. A crash or
                # lost response must never turn this allowance into another call.
                self.job.setdefault("refusal_retries", {})[identity] = params
                self.job["states"][identity] = {"state": "sending", "message": "Clarifying the translation context once."}
                self.save("running", self.job["states"][identity]["message"])
                try:
                    response = self.provider.live(params)
                except Exception as exc:
                    status = getattr(exc, "status_code", None)
                    certain = type(status) is int and 400 <= status < 500
                    self.job["states"][identity] = {"state": "failed" if certain else "uncertain",
                        "message": "The clarification retry failed. Review the saved request before further paid work."}
                    self.save("needs_attention" if certain else "uncertain", self.job["states"][identity]["message"])
                    return
                self.accept(identity, response)
        self.finish()

    def batch(self):
        if not self.job["batches"]:
            pending = [row for row in self.plan["requests"] if self.job["states"][row["id"]]["state"] == "pending"]
            limit = self.plan["batch_limits"]
            import json
            chunks, chunk, size, tokens = [], [], 0, 0
            schema = None
            same_schema = (self.plan['configuration'].get('openrouterStructuredOutputs')
                           and self.plan['configuration']['model'].startswith('google/'))
            token_limit = limit[2] if len(limit) > 2 else None
            for index, row in enumerate(pending):
                item = {"custom_id": "dtl-" + self.job["id"][:12] + "-" + str(index), "request": row["id"]}
                length = len(json.dumps(row["params"], ensure_ascii=False).encode("utf-8")) + 1024
                request_tokens = row.get("input_tokens", 0)
                if length > limit[1] or token_limit and request_tokens > token_limit:
                    raise ValueError("A request exceeds the provider's Batch file limit. Split the scene with source context.")
                if chunk and (len(chunk) >= limit[0] or size + length > limit[1] or token_limit and tokens + request_tokens > token_limit
                              or same_schema and schema != row['params'].get('response_format')):
                    chunks.append({"state": "pending", "id": "", "items": chunk})
                    chunk, size, tokens = [], 0, 0
                chunk.append(item)
                schema = row['params'].get('response_format')
                size += length
                tokens += request_tokens
            if chunk:
                chunks.append({"state": "pending", "id": "", "items": chunk})
            self.job["batches"] = chunks
            self.save()
        for chunk in self.job["batches"]:
            if chunk["state"] in {"complete", "canceled", "rejected"}:
                continue
            if self.store.stopped(self.job["id"]):
                self.save("stopped", "Polling stopped. Saved provider jobs remain available for collection.")
                return
            if chunk["state"] == "submitting" and not chunk["id"]:
                for item in chunk["items"]:
                    self.job["states"][item["request"]] = {"state": "uncertain", "message": "Attach the matching provider job before resuming."}
                self.save("uncertain", "Submission may have succeeded; a provider job ID must be reconciled.")
                return
            cancel = self.store.cancel_requested(self.job["id"])
            if cancel and not chunk["id"]:
                chunk["state"] = "canceled"
                for item in chunk["items"]:
                    self.job["states"][item["request"]] = {"state": "failed", "message": "Canceled before submission; no request was sent."}
                self.save()
                continue
            if not chunk["id"]:
                self.validate_current()
                # Durable intent comes before the call, including each exact correlation ID.
                chunk["state"] = "submitting"
                for item in chunk["items"]:
                    self.job["states"][item["request"]] = {"state": "queued", "message": "Submitting provider job."}
                self.save("running", "Submitting a provider batch.")
                try:
                    value = self.provider.submit([{"custom_id": item["custom_id"], "params": self.requests[item["request"]]["params"]}
                                                  for item in chunk["items"]])
                    chunk.update(id=value["id"], state="submitted")
                    self.save()
                except Exception as exc:
                    code = getattr(exc, "status_code", None)
                    certain = type(code) is int and 400 <= code < 500
                    for item in chunk["items"]:
                        self.job["states"][item["request"]] = {"state": "failed" if certain else "uncertain",
                            "message": "Provider rejected submission (HTTP " + str(code) + ")." if certain else "Submission outcome is uncertain; inspect the provider job list."}
                    if certain:
                        chunk["state"] = "rejected"
                    self.save("needs_attention" if certain else "uncertain", "Review the rejected submission." if certain else "The provider submission must be reconciled before retrying.")
                    return
            if cancel and not chunk.get("cancel_requested"):
                try:
                    self.provider.cancel(chunk["id"])
                except Exception as exc:
                    chunk["cancel_error"] = type(exc).__name__
                chunk["cancel_requested"] = True
                self.save()
            status = self.provider.status(chunk["id"])
            chunk.update(api_status=status["api_status"], counts=status["counts"])
            if not status["ended"]:
                self.save("waiting", "Provider batch is still processing." if not cancel else
                          "Cancellation requested. Waiting for the provider's final status and any completed results.")
                return
            if status["terminal_failure"]:
                mapping = {item["custom_id"]: item["request"] for item in chunk["items"]}
                responses, errors, usage = self.provider.collect_terminal(chunk["id"], mapping)
                matched = set(responses) | {mapping[identity] for identity in errors if identity in mapping}
                if chunk.get("attached") and matched != set(mapping.values()):
                    chunk["state"] = "unmatched"
                    for item in chunk["items"]:
                        if item["request"] not in matched:
                            self.job["states"][item["request"]] = {"state": "uncertain", "message": "The attached terminal job did not verify this request ID."}
                    for identity, response in responses.items():
                        self.accept(identity, response)
                    self.save("uncertain", "Verify the attached provider job before preparing any retry.")
                    return
                for identity, response in responses.items():
                    self.accept(identity, response)
                for item in chunk["items"]:
                    if self.job["states"][item["request"]]["state"] != "accepted":
                        self.job["states"][item["request"]] = {"state": "failed", "message": "Provider job ended with " + status["api_status"] + "."}
                chunk.update(state="complete", usage=usage)
                self.save("needs_attention", "The provider batch failed. Review remaining work before paying for a retry.")
                return
            mapping = {item["custom_id"]: item["request"] for item in chunk["items"]}
            responses, errors, usage = self.provider.collect(chunk["id"], mapping)
            known_errors = {mapping[identity] for identity in errors if identity in mapping}
            unmatched = set(mapping.values()) - set(responses) - known_errors
            if unmatched:
                for identity in unmatched:
                    if self.job["states"][identity]["state"] != "accepted":
                        self.job["states"][identity] = {"state": "uncertain", "message": "The provider results did not identify this request. Reconcile the job; do not resubmit it."}
                for identity, response in responses.items():
                    if identity in mapping.values():
                        self.accept(identity, response)
                chunk["state"] = "unmatched"
                self.save("uncertain", "Returned request IDs are incomplete or belong to another job. Attach the matching job before proceeding.")
                return
            if self.plan['configuration'].get('refusalRetry') == REFUSAL_POLICY and not cancel:
                from contextlib import contextmanager
                from .batch_refusals import advance
                @contextmanager
                def retry_commit():
                    if self.store.stopped(self.job['id']):
                        raise ValueError('Stopped before submitting a clarification Batch.')
                    self.validate_current()
                    yield
                retried = advance(self.folder, chunk['id'],
                    {item['request']: self.requests[item['request']]['params'] for item in chunk['items']},
                    responses, usage, self.provider, limits=self.plan['batch_limits'],
                    input_tokens=getattr(self.provider, 'input_tokens', lambda _: 0), commit=retry_commit)
                chunk['clarification_batches'] = retried['batches']
                if not retried['ready']:
                    usage_keys = set(usage).union(*(batch.get('usage', {}) for batch in retried['batches']))
                    chunk['usage'] = {key: usage.get(key, 0) + sum(batch.get('usage', {}).get(key, 0) for batch in retried['batches'])
                                      for key in usage_keys}
                    for identity, response in responses.items():
                        if not refused(response, self.requests[identity]['sources'].values()):
                            self.accept(identity, response)
                    self.record_batch_usage()
                    self.save('uncertain' if retried.get('uncertain') else 'waiting',
                              'Reconcile the clarification Batch submission.' if retried.get('uncertain') else
                              'Waiting for the Batch clarification of refused requests.')
                    return
                responses, usage = retried['responses'], retried['usage']
            for item in chunk["items"]:
                identity = item["request"]
                if identity in responses:
                    self.accept(identity, responses[identity])
                elif self.job["states"][identity]["state"] != "accepted":
                    self.job["states"][identity] = {"state": "failed", "message": "No successful response was returned for this request."}
            chunk.update(state="complete", usage=usage)
            self.record_batch_usage()
            self.save()
            if any(self.job["states"][item["request"]]["state"] == "failed" for item in chunk["items"]):
                self.save("needs_attention", "Some returned translations need attention. Later batches have not been submitted.")
                return
        self.finish()

    def finish(self):
        states = {row["state"] for row in self.job["states"].values()}
        if states <= {"accepted"}:
            self.save("complete", "All requested translations are saved. Injection and runtime QA remain separate checkpoints.")
        else:
            self.save("uncertain" if "uncertain" in states else "needs_attention", "Review unresolved requests before continuing.")

    def step(self):
        self.recover()
        if any(row["state"] == "uncertain" for row in self.job["states"].values()):
            self.finish()
            return
        if self.plan["configuration"]["mode"] == "batch":
            self.batch()
        else:
            self.live()
