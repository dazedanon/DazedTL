"""What a provider reads in the requests built for a model.

Both methods' estimates count the text of each request's messages, which the
engine builds the same way for most models of a connection; some model
families shape it differently, such as GPT-5.6's separately cached
instructions. A sample request shows which way a model goes without building
a game's requests again.
"""

import json
from functools import lru_cache


def request_text(configuration):
    """The text of a sample request built under these settings."""
    return _sample(
        configuration["model"], configuration["protocol"], configuration["endpoint"]
    )


@lru_cache(maxsize=64)
def _sample(model, protocol, endpoint):
    from util.translation import buildOpenAIRequest

    params = buildOpenAIRequest(
        "System",
        "User",
        "History",
        0,
        "json",
        model,
        numLines=1,
        vocab_text="Vocabulary",
        api_provider=protocol,
        request_instructions="Instructions",
        api_url=endpoint,
    )
    return json.dumps(params["messages"], ensure_ascii=False, sort_keys=True)
