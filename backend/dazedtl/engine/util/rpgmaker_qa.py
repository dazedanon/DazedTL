"""Text QA's former single module, kept so existing callers and the engine's
scripts/rpgmaker_qa.py keep working: it only re-exports the names they use
from util.qa, where the code lives (see util/qa/__init__.py). New code
imports from util.qa's modules, and a test patches a name in the module that
uses it, since a re-exported name is a copy of the binding.
"""

from __future__ import annotations

from util.rpgmaker_qa_manifest import build_manifest
from util.qa.schema import (
    ADDED_BATTLER_NAME,
    BUNDLE_SCHEMA,
    _canonical_bytes,
    CHECKPOINT_SCHEMA,
    CORRECTION_MAP_SCHEMA,
    DECLINE_REASON_LIMIT,
    DEEP_RESULT_SCHEMA,
    DEFAULT_DEEP_CHAR_BUDGET,
    DEFAULT_DEEP_ITEM_LIMIT,
    DEFAULT_HELPER,
    DEFAULT_SCREEN_CHAR_BUDGET,
    DEFAULT_SCREEN_ITEM_LIMIT,
    EDITORIAL_JUDGMENT_CATEGORIES,
    EDITORIAL_RESULT_SCHEMA,
    FINDING_CATEGORIES,
    FINDINGS_SCHEMA,
    FINISHED_STATUSES,
    LINT_ITEM_LIMIT,
    QA_RULES_VERSION,
    QAResultError,
    REGRESSION_SCHEMA,
    REVIEW_STAGES,
    SCREEN_RESULT_SCHEMA,
    _sha256,
    SUMMARY_LIMIT,
    SWEEP_RESULT_SCHEMA,
    TASK_SCHEMA,
    task_sha256,
)
from util.qa.storage import (
    ANSWERS,
    answers,
    ANSWERS_FILE,
    ANSWERS_SCHEMA,
    _decisions,
    DECISIONS_FILE,
    DECISIONS_SCHEMA,
    JUDGED_BEFORE,
    read_task,
    rules_changed,
    _slug,
    _task_lock,
)
from util.qa.records import _set_pointer
from util.qa.fitting import (
    APPROVED_NONBLOCKING_MECHANICAL_FLAGS,
    _box,
    correction_problems,
    _fit,
    _operation_writes,
    _record_problems,
    task_layout,
    _written,
)
from util.qa.selection import (
    FORCED_DEEP_EVENT_CODES,
    FORCED_DEEP_MECHANICAL_FLAGS,
)
from util.qa.interface import (
    CAPTURE_RECORD,
    CAPTURE_SCHEMA,
    _fit_checks,
    interface_capture,
    INTERFACE_FOLDER,
    interface_places,
    INTERFACE_PLACES_LISTED,
    RECAPTURE_OBSERVER,
)
from util.qa.ledger import (
    BASELINE_FOLDER,
    JUDGED_DISPOSITIONS,
    _pair_key,
    REVIEWED_FILE,
    REVIEWED_SCHEMA,
    _task_ledger,
    TASK_LEDGER_VERSION,
)
from util.qa.bundles import (
    _bundle_deep,
    DECLINES_TO_SET_ASIDE,
    DEEP_LOCATOR_LIMIT,
    SCREEN_CHECK_MISSES,
    SCREEN_CHECK_SHARE,
    _split_declined,
)
from util.qa.validation import (
    DEEP_DISPOSITIONS,
    MOTIF_DISPOSITIONS,
    OBSERVATION_NOTE_LIMIT,
    SCREEN_VERDICTS,
    SEVERITIES,
    SOURCE_FIX_KINDS,
    SUMMARY_DISPOSITIONS,
)
from util.qa.pace import (
    ACTIVE_WORKER_SECONDS,
    DEFAULT_SECONDS_PER_ITEM,
    _estimate,
    ONE_AT_A_TIME_BELOW,
    ONE_AT_A_TIME_BUNDLES,
    refresh_kept,
    STALL_MINIMUM_SECONDS,
    status,
)
from util.qa.advance import advance, EARLY_DEEP_BATCH
from util.qa.findings import SOURCE_FIX_ALLOWED_FLAGS
from util.qa.editorial import (
    EDITORIAL_CONFLICT_ROUNDS,
    EDITORIAL_VERDICTS,
    finalize,
    _judged_findings,
)
from util.qa.acceptance import (
    accept_result,
    changed_names,
    corrected_lines,
    held_names,
    observed_lines,
    observed_names,
    record_observation,
)
from util.qa.briefs import (
    brief,
    _BRIEF_SECTIONS,
    context_view,
    handoff_text,
    QA_ROLES,
    render_bundle,
    runtime_command,
    shell_argument,
)
from util.qa.claims import (
    accept_text,
    claim,
    decline_items,
    next_bundle,
    release_bundle,
    RUN_BUNDLES,
)
from util.qa.apply import (
    answer,
    apply_loaded_correction_map,
    correction_map,
    record_decision,
)
from util.qa.prepare import (
    CURRENT_FILE,
    _earlier_reviews,
    find_latest_task,
    inventory_matches,
    prepare_task,
    replaced_by,
    require_current,
    SCOPE_FILE,
)
from util.qa.rebuild import rebuild_deep_from_screen
