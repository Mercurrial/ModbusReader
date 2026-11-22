# Example addresses belong to example-map.json, not to a real device.
for i in range(10):
    record(sample=i, time=timestamp(), temperature=read("Temperature") * 0.1)
    wait(1)
