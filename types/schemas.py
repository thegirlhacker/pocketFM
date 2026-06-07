from pydantic import BaseModel
from typing import List, Optional

class FileChange(BaseModel):
    filepath: str
    original_snippet: str
    new_content: str

class IssuePlan(BaseModel):
    understanding: str
    files_to_modify: List[str]
    strategy: str

class ValidationResult(BaseModel):
    success: bool
    output: str
    error: Optional[str] = None
