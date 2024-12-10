def run_format(periods):
    # Sort the periods by start time
    periods.sort(key=lambda x: x["start"])
    merged_periods = []
    
    for period in periods:
        if not merged_periods or merged_periods[-1]["end"] < period["start"]:
            # Add new interval if there's no overlap/contiguity
            merged_periods.append({"start": period["start"], "end": period["end"]})
        else:
            # Merge with the last interval if there's overlap/contiguity
            merged_periods[-1]["end"] = max(merged_periods[-1]["end"], period["end"])
    
    return merged_periods
