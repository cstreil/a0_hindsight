"""
Optional Hindsight dreaming extension.

Runs the dreaming workflow opportunistically after normal foreground turns when
the configured interval is due. The actual work runs in a background task so it
does not add prompt overhead to the current response.
"""

import asyncio
import os
import sys
from helpers import errors
from helpers.extension import Extension
from agent import LoopData, AgentContextType

plugin_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if plugin_base not in sys.path:
    sys.path.insert(0, plugin_base)

from usr.plugins.a0_hindsight.helpers import hindsight_dreaming, hindsight_helper


class HindsightDreaming(Extension):

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return

        context = self.agent.context
        if not hasattr(context, "agent0"):
            return
        if context.type == AgentContextType.BACKGROUND:
            return
        if not hindsight_helper.is_configured(context):
            return

        config = hindsight_helper._get_plugin_config(self.agent)
        if not config.get("hindsight_dreaming_enabled", False):
            return
        if hindsight_helper.is_scheduled_task_turn(context, loop_data, self.agent):
            return

        state = getattr(context, "_hindsight", None)
        if state is None:
            context._hindsight = {}
            state = context._hindsight
        if state.get("dreaming_task_running"):
            return

        if not hindsight_dreaming.due_for_run(config, hindsight_dreaming.load_state()):
            return

        try:
            state["dreaming_task_running"] = True
            if config.get("hindsight_operation_logging", True):
                hindsight_helper._log(context, "Dreaming workflow due; running in background", "util")
            task = asyncio.create_task(asyncio.to_thread(
                hindsight_dreaming.run_dreaming,
                context,
                self.agent,
                False,
            ))
            task.add_done_callback(lambda done: self._done(done, context, state))
        except RuntimeError:
            state["dreaming_task_running"] = False

    @staticmethod
    def _done(task, context, state):
        state["dreaming_task_running"] = False
        try:
            result = task.result()
            if not result.get("ok"):
                hindsight_helper._log(context, f"Dreaming workflow error: {result.get('error') or result}", "warning")
            elif result.get("synthesized"):
                hindsight_helper._log(context, f"Dreaming synthesis retained as '{result.get('document_id')}'", "util")
            elif result.get("skipped"):
                hindsight_helper._log(context, f"Dreaming workflow skipped: {result.get('reason')}", "debug", debug_only=True)
            else:
                hindsight_helper._log(context, "Dreaming workflow completed without new synthesis", "util")
        except Exception as e:
            try:
                context.log.log(
                    type="warning",
                    heading="Hindsight dreaming background error",
                    content=errors.format_error(e),
                )
            except Exception:
                pass
