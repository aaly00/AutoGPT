from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Generic, Iterator, Optional

from forge.agent.components import ConfigurableComponent
from forge.agent.protocols import AfterExecute, AfterParse, MessageProvider
from forge.llm.prompting.utils import indent
from forge.llm.providers import ChatMessage, ChatModelProvider
from forge.llm.providers.multi import ModelName
from forge.models.config import ComponentConfiguration

from .model import AP, ActionResult, Episode, EpisodicActionHistory


class ActionHistoryConfiguration(ComponentConfiguration):
    max_tokens: int = 1024
    browse_spacy_language_model: str = "en_core_web_sm"


class ActionHistoryComponent(MessageProvider, AfterParse, AfterExecute, Generic[AP], ConfigurableComponent[ActionHistoryConfiguration]):
    """Keeps track of the event history and provides a summary of the steps."""

    def __init__(
        self,
        event_history: EpisodicActionHistory[AP],
        count_tokens: Callable[[str], int],
        llm_model_name: ModelName,
        llm_provider: ChatModelProvider,
        config: Optional[ActionHistoryConfiguration] = None,
    ) -> None:
        super().__init__(config or ActionHistoryConfiguration())
        self.event_history = event_history
        self.count_tokens = count_tokens
        self.model_name = llm_model_name
        self.llm_provider = llm_provider

    def get_messages(self) -> Iterator[ChatMessage]:
        if progress := self._compile_progress(
            self.event_history.episodes,
            self.config.max_tokens,
            self.count_tokens,
        ):
            yield ChatMessage.system(f"## Progress on your Task so far\n\n{progress}")

    def after_parse(self, result: AP) -> None:
        self.event_history.register_action(result)

    async def after_execute(self, result: ActionResult) -> None:
        self.event_history.register_result(result)
        await self.event_history.handle_compression(
            self.llm_provider, self.model_name, self.config.browse_spacy_language_model
        )

    def _compile_progress(
        self,
        episode_history: list[Episode],
        max_tokens: Optional[int] = None,
        count_tokens: Optional[Callable[[str], int]] = None,
    ) -> str:
        if max_tokens and not count_tokens:
            raise ValueError("count_tokens is required if max_tokens is set")

        steps: list[str] = []
        tokens: int = 0
        n_episodes = len(episode_history)

        for i, episode in enumerate(reversed(episode_history)):
            # Use full format for the latest 4 steps, summary or format for older steps
            if i < 4 or episode.summary is None:
                step_content = indent(episode.format(), 2).strip()
            else:
                step_content = episode.summary

            step = f"* Step {n_episodes - i}: {step_content}"

            if max_tokens and count_tokens:
                step_tokens = count_tokens(step)
                if tokens + step_tokens > max_tokens:
                    break
                tokens += step_tokens

            steps.insert(0, step)

        return "\n\n".join(steps)