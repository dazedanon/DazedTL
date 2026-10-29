"""The resend rule of a Guided run frozen with settings/preferences RESENDS,
which the engine's retry follows (util/translation _send_live): a failed Live
request is sent again only when transmission.resendable reads its tries as
unprocessed and worth another try. Any other failure, such as a gateway's
timeout, fails the call at once, and its record reads uncertain
(run_evidence)."""

from functools import partial

from dazedtl.settings.preferences import RESENDS

from . import transmission

LAYER = "resends"


def guarded(translation, native, *args, **kwargs):
    """A Live request whose tries all failed unprocessed, the last one for
    now, fails with the engine's RequestUnprocessedError, the one error its
    retry sends again; any other error passes as it is."""
    with transmission.watching() as tries:
        try:
            return native(*args, **kwargs)
        except Exception as error:
            if transmission.resendable(tries):
                raise translation.RequestUnprocessedError(str(error)) from error
            raise


def configure(translation, policy):
    """Follows the rule in a run frozen with it. The layer watches every try
    its call sends, so its place among the other layers does not matter."""
    translation.RESENDS = bool(policy and policy.get("resends") == RESENDS)
    if not translation.RESENDS:
        translation.translateText.remove(LAYER)
        return
    transmission.install()
    translation.translateText.layer(LAYER, partial(guarded, translation))
