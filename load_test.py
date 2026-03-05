from locust import HttpUser, between, task
import random


class DashboardUser(HttpUser):
    wait_time = between(2, 5)

    def on_start(self):
        self.machines = ["M231-11", "M356-57", "M471-23", "M607-30", "M612-33"]
        self.parts = {
            "M231-11": ["8-1419168-4", "1411223-1"],
            "M356-57": ["8-1419168-4"],
            "M471-23": ["8-1419168-4"],
            "M607-30": ["8-1419168-4"],
            "M612-33": ["2447665-1", "2177007-2", "1-1452341-2"],
        }

    @task(5)
    def load_chart_data(self):
        machine = random.choice(self.machines)
        part = random.choice(self.parts.get(machine, [""]))
        self.client.get(
            f"/api/machines/{machine}/chart-data-v2",
            params={
                "part_number": part,
                "horizon_minutes": 60,
                "history_limit": 500,
                "shift_hours": 24,
            },
            name="/api/machines/{machine_id}/chart-data-v2",
        )

    @task(3)
    def load_control_room(self):
        machine = random.choice(self.machines)
        self.client.get(
            f"/api/machines/{machine}/control-room",
            params={"horizon_minutes": 60, "history_window": 240},
            name="/api/machines/{machine_id}/control-room",
        )

    @task(1)
    def load_metrics(self):
        self.client.get("/api/ai/metrics-dashboard", name="/api/ai/metrics-dashboard")
