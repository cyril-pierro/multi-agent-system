from abc import ABCMeta, abstractmethod
from typing import Any, Callable


class AgentInterface(metaclass=ABCMeta):

    @property
    @abstractmethod
    def agent_id(self) -> str:
        pass

    @classmethod
    def _generate_system_prompt(cls) -> str:
        pass

    @classmethod
    def _generate_payload(cls) -> dict[str, Any]:
        pass

    @classmethod
    def run(cls, stream_func: Callable) -> Any:
        pass
