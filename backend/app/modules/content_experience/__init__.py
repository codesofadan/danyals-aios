"""The human half of the Experience gate.

The doctrine pipeline HALTS every page whose first-party facts nobody has supplied
(Law 16, the owner's "hard halt, no exceptions"), writes the interview questions
into `sme_slots`, and stops. This module is where an operator reads those
questions and answers them - the only thing that can clear the halt.

WHY IT IS NOT PART OF content_planning, whose tables these are: that module's
router is READ-ONLY by design and a test enforces it, because an endpoint that
enqueued production would sit in FRONT of the pipeline's gates. Answering the
questionnaire does re-queue the page, so it does not belong under that contract -
even though the resumed run re-runs the SME gate first and will halt again if the
answers did not actually complete the dossier. The boundary stays enforceable and
this concern gets its own door.
"""

from app.modules.content_experience.router import router

__all__ = ["router"]
