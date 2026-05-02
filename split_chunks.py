import json

with open("advisors_extracted.json") as f:
    data = json.load(f)

chunk_size = 40

for i in range(0, len(data), chunk_size):
    chunk = data[i:i+chunk_size]
    with open(f"chunk_{i//chunk_size + 1}.json", "w") as out:
        json.dump(chunk, out, indent=2)

print("Chunks created!")