"""Transport-independent acceptance, submission journaling, and safe resume."""

from dazedtl.storage import write_json
from .files import read_json
from .results import Results


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

    def response_path(self, identity):
        from .files import digest
        return self.folder / "responses" / (digest(identity) + ".json")

    def accept(self, identity, response):
        request = self.requests[identity]
        write_json(self.response_path(identity), response)
        self.record_usage(identity, response)
        try:
            self.results.accept(request, response["text"], {"run_id": self.job["id"],
                                "mode": self.plan["configuration"]["mode"], "model": self.plan["configuration"]["model"]})
            self.job["states"][identity] = {"state": "accepted", "message": ""}
        except ValueError as exc:
            self.job["states"][identity] = {"state": "failed", "message": str(exc)}
        self.save()
        self.checkpoint()

    def record_usage(self, identity, response):
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
        self.save()

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
        self.finish()

    def batch(self):
        if not self.job["batches"]:
            pending = [row for row in self.plan["requests"] if self.job["states"][row["id"]]["state"] == "pending"]
            limit = self.plan["batch_limits"]
            import json
            chunks, chunk, size, tokens = [], [], 0, 0
            token_limit = limit[2] if len(limit) > 2 else None
            for index, row in enumerate(pending):
                item = {"custom_id": "dtl-" + self.job["id"][:12] + "-" + str(index), "request": row["id"]}
                length = len(json.dumps(row["params"], ensure_ascii=False).encode("utf-8")) + 1024
                request_tokens = row.get("input_tokens", 0)
                if length > limit[1] or token_limit and request_tokens > token_limit:
                    raise ValueError("A request exceeds the provider's Batch file limit. Split the scene with source context.")
                if chunk and (len(chunk) >= limit[0] or size + length > limit[1] or token_limit and tokens + request_tokens > token_limit):
                    chunks.append({"state": "pending", "id": "", "items": chunk})
                    chunk, size, tokens = [], 0, 0
                chunk.append(item)
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
            for item in chunk["items"]:
                identity = item["request"]
                if identity in responses:
                    self.accept(identity, responses[identity])
                elif self.job["states"][identity]["state"] != "accepted":
                    self.job["states"][identity] = {"state": "failed", "message": "No successful response was returned for this request."}
            chunk.update(state="complete", usage=usage)
            self.job["usage"] = {key: sum(item.get("usage", {}).get(key, 0) for item in self.job["batches"]) for key in usage}
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
