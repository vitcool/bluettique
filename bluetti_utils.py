async def fetch_bluetti_status(bluettiController):
    bluetti_status = await bluettiController.get_status()
    if bluetti_status:
        return {
            "battery_percent": bluetti_status["total_battery_percent"],
            "ac_output_on": bluetti_status["ac_output_on"],
            "dc_output_on": bluetti_status["dc_output_on"],
            "ac_output_power": bluetti_status["ac_output_power"],
            "dc_output_power": bluetti_status["dc_output_power"],
            "ac_input_power": bluetti_status["ac_input_power"],
            "dc_input_power": bluetti_status.get("dc_input_power", 0),
        }
    return None