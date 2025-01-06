import requests
import json
import logging


def fetch_electricity_outages(fetch_function=requests.get):
    url = "https://api.yasno.com.ua/api/v1/pages/home/schedule-turn-off-electricity"

    try:
        # Fetch data from the API
        response = fetch_function(url)
        response.raise_for_status()  # Raise an exception for HTTP errors

        # Parse the JSON response
        data = response.json()

        # Extract the first group ("1") and filter for "DEFINITE_OUTAGE"
        result = []
        for component in data.get("components", []):
            if component.get(
                "template_name"
            ) == "electricity-outages-daily-schedule" and "kiev" in component.get(
                "available_regions", []
            ):
                outages = (
                    component.get("dailySchedule", {})
                    .get("kiev", {})
                    .get("today", {})
                    .get("groups", {})
                    .get("1.2", [])
                )
                result = [
                    entry for entry in outages if entry.get("type") == "DEFINITE_OUTAGE"
                ]
                break  # Exit once we've found the matching component

        # Return the result
        return result

    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return []
    except KeyError as e:
        print(f"Key error while processing data: {e}")
        return []
    
def mock_fetch_function(url):
    class MockResponse:
        def raise_for_status(self):
            pass  # Simulate no HTTP errors

        def json(self):
            # Mocked JSON response
            return {
                "components": [
                    {
                        "template_name": "electricity-outages-daily-schedule",
                        "available_regions": ["kiev"],
                        "dailySchedule": {
                            "kiev": {
                                "today": {
                                    "groups": {
                                        "1": [
                                            {"start": 6, "end": 7, "type": "DEFINITE_OUTAGE"},
                                            {"start": 7, "end": 8, "type": "DEFINITE_OUTAGE"},
                                            {"start": 11, "end": 13, "type": "DEFINITE_OUTAGE"},
                                            {"start": 13, "end": 14, "type": "DEFINITE_OUTAGE"},
                                            {"start": 14, "end": 15, "type": "DEFINITE_OUTAGE"},
                                            {"start": 15, "end": 16, "type": "DEFINITE_OUTAGE"}
                                        ]
                                    }
                                }
                            }
                        },
                    }
                ]
            }

    return MockResponse()
