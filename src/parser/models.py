from dataclasses import dataclass, field


@dataclass
class FileReference:
    file_path: str
    description: str = ""


@dataclass
class CodeBlock:
    code: str
    language: str = ""
    context_text: str = ""


@dataclass
class ToolCall:
    tool_id: str = ""
    tool_label: str = ""
    invocation_message: str = ""


@dataclass
class CopilotRequest:
    request_id: str
    seq_num: int
    user_message: str
    assistant_response: str = ""
    thinking_text: str = ""
    timestamp: int | None = None
    file_references: list[FileReference] = field(default_factory=list)
    code_blocks: list[CodeBlock] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    agent_id: str | None = None
    model_id: str | None = None
    timing_first_progress: int | None = None
    timing_total_elapsed: int | None = None


@dataclass
class CopilotSession:
    session_id: str
    source_file: str
    file_mtime: float
    requests: list[CopilotRequest] = field(default_factory=list)
    workspace_folder: str | None = None
    workspace_hash: str | None = None
    creation_date: int | None = None
    custom_title: str | None = None
    model_id: str | None = None
    initial_location: str = "panel"

    @property
    def project_name(self) -> str | None:
        if not self.workspace_folder:
            return None
        # Extract last segment from file URI or path
        folder = self.workspace_folder
        # Handle file:///c%3A/Users/.../ProjectName URIs
        if folder.startswith("file://"):
            folder = folder.split("file://")[-1]
            # URL-decode common chars
            folder = folder.replace("%3A", ":").replace("%20", " ")
        return folder.rstrip("/\\").split("/")[-1].split("\\")[-1] or None
