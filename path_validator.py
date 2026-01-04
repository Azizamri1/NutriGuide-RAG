import yaml
from pathlib import Path

with open('manifests/corpus_manifest.yaml') as f:
    corpus = yaml.safe_load(f)

for doc in corpus:
    file_path = Path(doc['path'])
    if not file_path.exists():
        print(f"❌ MISSING: {doc['id']} at {file_path}")
    else:
        print(f"✅ FOUND: {doc['id']}")