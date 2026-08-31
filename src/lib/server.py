import requests


class Server:
    def __init__(self, ip, id, name, token):
        self.ip = ip.rstrip("/")
        self.id = id
        self.name = name
        self.token = token

        self.session = requests.Session()

        self.status = "Disconnected"

        self.experiments = None

    def login(self):
        response = self.session.post(
            f"{self.ip}/devices/login",
            data={
                "cell_id": self.id,
                "token": self.token,
            },
            timeout=10,
        )

        response.raise_for_status()
        self.status = "Connected"

        return response.json()

    def get_available_experiments(self):
        response = self.session.get(
            f"{self.ip}/devices/get_available_experiments",
            params={
                "token": self.token,
            },
            timeout=10,
        )
        response.raise_for_status()

        self.experiments = response.json()
        
        return response.json()

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
        return response.json()