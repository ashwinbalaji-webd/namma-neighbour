class BaseSMSBackend:
    def send(self, phone: str, otp: str) -> None:
        raise NotImplementedError
