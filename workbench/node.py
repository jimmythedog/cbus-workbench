from dataclasses import dataclass, field


@dataclass
class Node:
    number: int
    module_type: str
    can_id: int
    firmware: str
    has_mdf: bool
    nv_values: dict[int, int] = field(default_factory=dict)
    nv_descriptions: dict[int, str] = field(default_factory=dict)
