"""Pipeline 领域事件定义。

所有 pipeline 函数 yield PipelineEvent，由 stream_routes 统一转换成 SSE。
Pipeline 不知道 HTTP / SSE / FastAPI。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineEvent:
    type: str          # progress / result / chunk / mindmap / notes_text / warn / error / done
    data: dict[str, Any] = field(default_factory=dict)
