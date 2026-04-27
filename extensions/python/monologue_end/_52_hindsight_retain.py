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

        scheduled_task = hindsight_helper.get_scheduled_task(context, loop_data)
        if scheduled_task:
            try:
                asyncio.create_task(
                    self._retain_scheduled_task_log(self.agent, context, scheduled_task)
                )
            except RuntimeError:
                pass
            return

        chatlog = hindsight_helper.build_chatlog(self.agent)
        if not chatlog:
            return
        chatlog_count = len(chatlog)
        chatlog_chars = hindsight_helper.chatlog_char_count(chatlog)

        state = getattr(context, "_hindsight", None)
        if state is None:
            context._hindsight = {}
            state = context._hindsight
        if state.get("last_retain_seen_count") == chatlog_count:
            return
        state["last_retain_seen_count"] = chatlog_count

        last_retained_count = int(state.get("last_retained_chatlog_count", 0) or 0)
        last_retained_chars = int(state.get("last_retained_chatlog_chars", 0) or 0)
        new_messages = max(0, chatlog_count - last_retained_count)
        new_chars = max(0, chatlog_chars - last_retained_chars)
        min_messages = int(config.get("hindsight_retain_min_messages", 3) or 0)
        min_chars = int(config.get("hindsight_retain_min_chars", 800) or 0)

        message_threshold_met = min_messages > 0 and new_messages >= min_messages
        char_threshold_met = min_chars > 0 and new_chars >= min_chars
        thresholds_disabled = min_messages <= 0 and min_chars <= 0
        if not (thresholds_disabled or message_threshold_met or char_threshold_met):
            return

        try:
            task = asyncio.create_task(self._retain_to_hindsight(self.agent, context, config))
            task.add_done_callback(
                lambda done: self._mark_retained(done, state, chatlog_count, chatlog_chars)
            )
        except RuntimeError:
            pass

    @staticmethod
    def _mark_retained(task, state, chatlog_count, chatlog_chars):
        try:
            if task.result():
                state["last_retained_chatlog_count"] = chatlog_count
                state["last_retained_chatlog_chars"] = chatlog_chars
        except Exception:
            pass

    @staticmethod
    async def _retain_to_hindsight(agent, context, config):
        try:
            return await hindsight_helper.retain_chatlog(context=context, agent=agent)
        except Exception as e:
            try:
                context.log.log(
                    type="warning",
                    heading="Hindsight retain background error",
                    content=errors.format_error(e),
                )
            except Exception:
                pass

    @staticmethod
    async def _retain_scheduled_task_log(agent, context, scheduled_task):
        try:
            return await hindsight_helper.retain_scheduled_task_log(
                context=context,
                agent=agent,
                task=scheduled_task,
            )
        except Exception as e:
            try:
                context.log.log(
                    type="warning",
                    heading="Hindsight scheduled task retain error",
                    content=errors.format_error(e),
                )
            except Exception:
                pass
