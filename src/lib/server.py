import requests


class Server:
    """HTTP client for the central DigiFlot Server.

    The legacy methods are intentionally kept intact. API-v2 methods are
    additive so the Edge can negotiate capabilities at runtime and fall back to
    the old flat experiment list when connected to an older Server.
    """

    def __init__(self, ip, id, name, token):
        self.ip = str(ip or "").rstrip("/")
        self.id = id
        self.name = name
        self.token = token

        self.session = requests.Session()

        self.status = "Disconnected"
        self.last_error = None
        self.experiments = None
        self.capabilities = {}
        self.api_version = 1

    def _set_connected(self):
        self.status = "Connected"
        self.last_error = None

    def _set_error(self, error):
        self.status = "Disconnected"
        self.last_error = str(error)

    def login(self):
        try:
            response = self.session.post(
                f"{self.ip}/devices/login",
                data={
                    "cell_id": self.id,
                    "token": self.token,
                },
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as error:
            self._set_error(error)
            raise

        capabilities = payload.get("capabilities") if isinstance(payload, dict) else None
        self.capabilities = capabilities if isinstance(capabilities, dict) else {}
        try:
            self.api_version = max(1, int(self.capabilities.get("device_api_version") or 1))
        except (TypeError, ValueError):
            self.api_version = 1

        self._set_connected()
        return payload

    # ------------------------------------------------------------------
    # Legacy API
    # ------------------------------------------------------------------

    def get_available_experiments(self):
        response = self.session.get(
            f"{self.ip}/devices/get_available_experiments",
            params={
                "token": self.token,
            },
            timeout=10,
        )
        response.raise_for_status()
        self._set_connected()

        self.experiments = response.json()
        return self.experiments

    def get_experiment(self, experiment_id):
        response = self.session.get(
            f"{self.ip}/devices/get_experiment",
            params={
                "id": experiment_id,
                "token": self.token,
            },
            timeout=10,
        )
        response.raise_for_status()
        self._set_connected()
        return response.json()

    # ------------------------------------------------------------------
    # Device API v2
    # ------------------------------------------------------------------

    def get_catalog(self):
        response = self.session.get(
            f"{self.ip}/devices/v2/catalog",
            params={"token": self.token},
            timeout=12,
        )
        response.raise_for_status()
        self._set_connected()
        return response.json()

    def get_experiment_v2(self, experiment_id):
        response = self.session.get(
            f"{self.ip}/devices/v2/experiments/{int(experiment_id)}",
            params={"token": self.token},
            timeout=12,
        )
        response.raise_for_status()
        self._set_connected()
        return response.json()

    def claim_execution(self, payload):
        body = dict(payload or {})
        body["token"] = self.token
        response = self.session.post(
            f"{self.ip}/devices/v2/executions/claim",
            json=body,
            timeout=12,
        )
        response.raise_for_status()
        self._set_connected()
        return response.json()

    def update_execution(self, client_execution_id, payload):
        body = dict(payload or {})
        body["token"] = self.token
        response = self.session.patch(
            f"{self.ip}/devices/v2/executions/client/{client_execution_id}",
            json=body,
            timeout=12,
        )
        response.raise_for_status()
        self._set_connected()
        return response.json()

    def report_location(self, client_execution_id, payload):
        body = dict(payload or {})
        body["token"] = self.token
        response = self.session.post(
            f"{self.ip}/devices/v2/executions/client/{client_execution_id}/locations",
            json=body,
            timeout=12,
        )
        response.raise_for_status()
        self._set_connected()
        return response.json()

    def sync_executions(self, executions):
        response = self.session.post(
            f"{self.ip}/devices/v2/sync",
            json={
                "token": self.token,
                "executions": list(executions or []),
            },
            timeout=30,
        )
        response.raise_for_status()
        self._set_connected()
        return response.json()

    def report_device_ip(self, ip_address):
        """Best-effort future-facing Edge-IP announcement.

        The Server endpoint is intentionally optional for now. Do not call
        ``raise_for_status`` here: a 404, 405, 5xx response or any future schema
        mismatch must never affect normal Edge synchronization.
        """
        try:
            return self.session.post(
                f"{self.ip}/devices/v2/ip",
                json={
                    "token": self.token,
                    "cell_id": self.id,
                    "name": self.name,
                    "ip": str(ip_address or "").strip() or None,
                },
                timeout=2,
            )
        except Exception:
            return None
