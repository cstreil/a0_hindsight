"""
Hermes-style Hindsight retain extension.

After a final Agent Zero response, retain one structured chatlog document using
a stable document_id. This replaces the previous utility-LLM extraction and
per-fragment retain behavior.
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

from usr.plugins.a0_hindsight.helpers import hindsight_helper


class HindsightRetain(Extension):

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
        if not config.get("hindsight_retain_enabled", True):
            return

        all_output = self.agent.history.output()
        state = getattr(context, "_hindsight", None)
        if state is None:
            context._hindsight = {}
            state = context._hindsight
        if state.get("last_retain_message_count") == len(all_output):
            return
        state["last_retain_message_count"] = len(all_output)

        try:
            asyncio.create_task(self._retain_to_hindsight(self.agent, context))
        except RuntimeError:
            pass

    @staticmethod
    async def _retain_to_hindsight(agent, context):
        try:
            log_item = context.log.log(type="util", heading="Retaining chatlog to Hindsight...")
            success = await hindsight_helper.retain_chatlog(context=context, agent=agent)
            bank_id = hindsight_helper.get_bank_id(context)
            if success:
                log_item.update(heading=f"Hindsight chatlog retained to bank '{bank_id}'")
            else:
                log_item.update(heading="Hindsight chatlog retain skipped or failed")
        except Exception as e:
            try:
                context.log.log(
                    type="warning",
                    heading="Hindsight retain background error",
                    content=errors.format_error(e),
                )
            except Exception:
                pass
