"""
Hermes-style Hindsight recall extension.

Runs at most once per user turn and injects recalled memory as ephemeral,
fenced context. It does not persist recalled memory in Agent Zero history or
reuse it across tool-loop iterations.
"""

import asyncio
import os
import sys
from helpers.extension import Extension
from agent import LoopData
from helpers import errors

plugin_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if plugin_base not in sys.path:
    sys.path.insert(0, plugin_base)

from usr.plugins.a0_hindsight.helpers import hindsight_helper

SEARCH_TIMEOUT = 20


class HindsightRecall(Extension):

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent:
            return

        context = self.agent.context
        if not hasattr(context, "agent0"):
            return
        if not hindsight_helper.is_configured(context):
            return

        config = hindsight_helper._get_plugin_config(self.agent)
        if not config.get("hindsight_recall_enabled", True):
            return

        user_message = loop_data.user_message
        user_key = getattr(user_message, "id", None) or (
            user_message.output_text() if user_message else ""
        )
        if not user_key:
            return

        state = getattr(context, "_hindsight", None)
        if state is None:
            context._hindsight = {}
            state = context._hindsight
        if state.get("last_recall_user_key") == user_key:
            return
        state["last_recall_user_key"] = user_key

        debug = bool(config.get("hindsight_debug", False))
        log_item = context.log.log(type="util", heading="Searching Hindsight memories...") if debug else None

        try:
            query = user_message.output_text().strip() if user_message else ""
            if len(query) < 3:
                if log_item:
                    log_item.update(heading="Insufficient query for Hindsight recall")
                return

            recall_result = await asyncio.wait_for(
                hindsight_helper.recall_memories(context, query),
                timeout=SEARCH_TIMEOUT,
            )

            if recall_result and recall_result.strip():
                if log_item:
                    log_item.update(heading="Hindsight memories found", content=recall_result[:500])
                hindsight_prompt = self.agent.read_prompt(
                    "hindsight.recall.md",
                    hindsight_memories=recall_result,
                )
                loop_data.extras_temporary["hindsight_memories"] = hindsight_prompt
            else:
                if log_item:
                    log_item.update(heading="No Hindsight memories found")

        except asyncio.TimeoutError:
            if log_item:
                log_item.update(heading="Hindsight recall timed out")
            else:
                context.log.log(type="warning", heading="Hindsight recall timed out")
        except Exception as e:
            context.log.log(
                type="warning",
                heading="Hindsight recall extension error",
                content=errors.format_error(e),
            )
