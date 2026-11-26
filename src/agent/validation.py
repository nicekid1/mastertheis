"""User-facing GIS validation, independent of UI and transport."""
class GISValidationError(ValueError):
    def __init__(self, code, en, fa, role=None):
        super().__init__(en)
        self.detail = {'code': code, 'en': en, 'fa': fa, 'role': role}


def public_error(detail=None):
    return detail or {
        'code': 'analysis_failed',
        'en': 'Analysis failed. Review the input layers and parameters; technical details are in the run report.',
        'fa': 'تحلیل انجام نشد. لایه‌های ورودی و پارامترها را بررسی کنید؛ جزئیات فنی در گزارش اجرا ثبت شده است.',
    }
