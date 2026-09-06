class InvestigationToolError(Exception):
    code = "tool_error"
    retryable = False
    blocked = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidToolArguments(InvestigationToolError):
    code = "invalid_arguments"
    blocked = True


class PermissionDenied(InvestigationToolError):
    code = "permission_denied"
    blocked = True


class UnsafeOperation(InvestigationToolError):
    code = "unsafe_operation"
    blocked = True


class ToolTimeout(InvestigationToolError):
    code = "timeout"
    retryable = True


class ServiceUnavailable(InvestigationToolError):
    code = "service_unavailable"
    retryable = True


class ResultTooLarge(InvestigationToolError):
    code = "result_too_large"
