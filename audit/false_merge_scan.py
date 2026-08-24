"""
False-Merge-Audit-Scan fuer ki-news story_registry_shadow.json
================================================================
Siehe Doku oben in dieser Datei fuer Kontext und Einschraenkungen.
"""
import json
import re


def load_patterns(entities_json_path, extra_entities=None):
    with open(entities_json_path) as f:
        ent_data = json.load(f)
    entities = list(ent_data['entities'])
    if extra_entities:
        entities += extra_entities

    def relaxed(alias):
        # deutsches Genitiv-s: '\bmeta\b' matcht 'Metas' nicht -> 's?' vor dem
        # schliessenden \b ergaenzen
        if alias.endswith(r'\b'):
            return alias[:-2] + r's?\b'
        return alias

    parent_of = {e['id']: (e.get('gehoert_zu') or e['id']) for e in entities}
    patterns = []
    for e in entities:
        alts = list(e['aliasse']) + [relaxed(a) for a in e['aliasse']]
        patterns.append((e['id'], re.compile('|'.join(alts), re.I)))
    return patterns, parent_of


DEFAULT_EXTRA_ENTITIES = [
    {'id': 'Intel', 'gehoert_zu': None, 'aliasse': [r'\bintel\b']},
    {'id': 'Kimi/Moonshot', 'gehoert_zu': None, 'aliasse': [r'\bkimi\b', r'moonshot']},
]


def scan(entities_json_path, story_registry_json_path, extra_entities=None):
    if extra_entities is None:
        extra_entities = DEFAULT_EXTRA_ENTITIES
    patterns, parent_of = load_patterns(entities_json_path, extra_entities)

    def entities_in(text):
        found = set()
        for eid, pat in patterns:
            if pat.search(text):
                found.add(parent_of.get(eid, eid))
        return found

    with open(story_registry_json_path) as f:
        data = json.load(f)
    stories = data['stories']

    multi = {sid: st for sid, st in stories.items() if len(st.get('titles', [])) >= 2}

    suspicious = []
    for sid, st in multi.items():
        titles = st['titles']
        links = st.get('links', [])
        ent_sets = [entities_in(t) for t in titles]
        n = len(titles)
        flagged_pairs = []
        for i in range(n):
            for j in range(i + 1, n):
                a, b = ent_sets[i], ent_sets[j]
                if a and b and a.isdisjoint(b):
                    flagged_pairs.append((i, j, sorted(a), sorted(b)))
        if flagged_pairs:
            suspicious.append({
                'story_id': sid,
                'titles': titles,
                'links': links,
                'flagged_pairs': flagged_pairs,
            })

    return {
        'total_active_stories': len(stories),
        'stories_with_multi_titles': len(multi),
        'suspicious_count': len(suspicious),
        'suspicious': suspicious,
    }


if __name__ == '__main__':
    import sys
    entities_path = sys.argv[1] if len(sys.argv) > 1 else 'entities.json'
    registry_path = sys.argv[2] if len(sys.argv) > 2 else 'story_registry_shadow.json'
    result = scan(entities_path, registry_path)
    print(f"Aktive Storys: {result['total_active_stories']}")
    print(f"Storys mit >=2 Titeln: {result['stories_with_multi_titles']}")
    print(f"Verdaechtig: {result['suspicious_count']}")
    for s in result['suspicious']:
        print('---', s['story_id'])
        for i, t in enumerate(s['titles']):
            print(f"  [{i}] {t}")
        for i, j, a, b in s['flagged_pairs']:
            print(f"  -> [{i}] {a} vs [{j}] {b}")
    print()
    print("WICHTIG: jeden Treffer vor einer Korrektur per Volltext-Artikel verifizieren,")
    print("nicht blind uebernehmen (siehe Einschraenkungen oben: st-02576 war ein False Positive).")
