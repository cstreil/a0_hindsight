"""
Optional Hindsight solution extraction.

Runs behind a cheap heuristic gate so the utility model is called only after
substantive tool-backed work, not after every chat turn.
"""

import asyncio
import os
import sys

from agent import AgentContextType, LoopData
from helpers import errors
from helpers.dirty_json import DirtyJson
from helpers.extension import Extension

plugin_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if plugin_base not in sys.path:
    sys.path.insert(0, plugin_base)

from usr.plugins.a0_hindsight.helpers import hindsight_helper


class HindsightSolutionExtract(Extension):

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
        if not config.get("hindsight_solution_extract_enabled", False):
            return
        if hindsight_helper.is_scheduled_task_turn(context, loop_data):
            return

        all_output = self.agent.history.output()
        chatlog = hindsight_helper.build_chatlog(self.agent)
        if not all_output or not chatlog:
            return

        state = getattr(context, "_hindsight", None)
        if state is None:
            context._hindsight = {}
            state = context._hindsight

        output_count = len(all_output)
        if state.get("last_solution_seen_output_count") == output_count:
            return
        state["last_solution_seen_output_count"] = output_count

        last_checked_output_count = int(state.get("last_solution_checked_output_count", 0) or 0)
        last_checked_chars = int(state.get("last_solution_checked_chatlog_chars", 0) or 0)
        new_output = all_output[last_checked_output_count:]
        new_tool_names = hindsight_helper.tool_names(new_output)
        current_chars = hindsight_helper.chatlog_char_count(chatlog)
        new_chars = max(0, current_chars - last_checked_chars)

        min_tool_calls = int(config.get("hindsight_solution_extract_min_tool_calls", 1) or 0)
        min_chars = int(config.get("hindsight_solution_extract_min_chars", 1200) or 0)
        tool_gate = min_tool_calls <= 0 or len(new_tool_names) >= min_tool_calls
        char_gate = min_chars <= 0 or new_chars >= min_chars
        if not (tool_gate and char_gate):
            return

        try:
            task = asyncio.create_task(
                self._extract_and_retain_solutions(
                    self.agent,
                    context,
                    config,
                    new_tool_names,
                )
            )
            task.add_done_callback(
                lambda done: self._mark_solution_checked(done, state, output_count, current_chars)
            )
        except RuntimeError:
            pass

    @staticmethod
    def _mark_solution_checked(task, state, output_count, current_chars):
        try:
            if task.result():
                state["last_solution_checked_output_count"] = output_count
                state["last_solution_checked_chatlog_chars"] = current_chars
        except Exception:
            pass

    @staticmethod
    async def _extract_and_retain_solutions(agent, context, config, new_tool_names):
        log_item = None
        try:
            if config.get("hindsight_operation_logging", True):
                log_item = context.log.log(
                    type="util",
                    heading="[Hindsight] Extract reusable solutions with utility model",
                )

            history_text = agent.concat_messages(agent.history)
            max_chars = int(config.get("hindsight_solution_extract_max_history_chars", 80000) or 80000)
            if len(history_text) > max_chars:
                history_text = history_text[-max_chars:]

            solutions_json = await agent.call_utility_model(
                system=agent.read_prompt("hindsight.solution_extract.sys.md"),
                message=history_text,
                background=True,
            )

            if config.get("hindsight_debug", False) and log_item:
                log_item.update(content=solutions_json)

            if not solutions_json or not isinstance(solutions_json, str):
                if log_item:
                    log_item.update(heading="[Hindsight] No solution extraction response")
                return True

            try:
                solutions = DirtyJson.parse_string(solutions_json.strip())
            except Exception as e:
                if log_item:
                    log_item.update(heading=f"[Hindsight] Failed to parse solution extraction: {e}")
                return True

            if solutions is None:
                solutions = []
            elif isinstance(solutions, dict):
                solutions = [solutions]
            elif isinstance(solutions, str):
                solutions = [solutions]
            elif not isinstance(solutions, list):
                solutions = []

            if not solutions:
                if log_item:
                    log_item.update(heading="[Hindsight] No reusable solutions found")
                return True

            retained = await hindsight_helper.retain_solutions(
                context=context,
                agent=agent,
                solutions=solutions,
                tool_names_used=new_tool_names,
            )
            if log_item:
                log_item.update(
                    heading=f"[Hindsight] {retained}/{len(solutions)} reusable solutions retained"
                )
            return True
        except Exception as e:
            try:
                context.log.log(
                    type="warning",
                    heading="Hindsight solution extraction error",
                    content=errors.format_error(e),
                )
            except Exception:
                pass
            return False
