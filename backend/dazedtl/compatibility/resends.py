"""The resend rule of a Guided run frozen with settings/preferences RESENDS:
the engine's retry sends a failed Live request again only when the provider
provably did not process it and another try may pass (transmission
resendable). The SDKs send nothing again themselves (the engine's RESENDS).
A request any try of which may have been billed, such as one a gateway timed
out after the model answered, fails its call at once; its record reads
uncertain for the user to check (run_evidence), and the run goes on with
its other requests."""

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
    translation.RESENDS = bool(policy and policy.get("resends") == RESENDS)
    if not translation.RESENDS:
        translation.translateText.remove(LAYER)
        return
    transmission.install()
    translation.translateText.layer(LAYER, partial(guarded, translation))
