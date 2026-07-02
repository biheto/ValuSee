from pydantic import BaseModel, Field


class ProjectAnalyzeRequest(BaseModel):
    project_path: str = Field(..., description="Local project directory to analyze")
    max_files: int = Field(default=500, ge=1, le=5000, description="Maximum files to scan")


class ProjectAnalyzeResponse(BaseModel):
    project_path: str
    project_name: str
    file_count: int
    directory_count: int
    tech_stack: list[str]
    key_files: list[str]
    modules: list[str]
    risks: list[str]
    suggestions: list[str]
    quality_score: int
    report_markdown: str
