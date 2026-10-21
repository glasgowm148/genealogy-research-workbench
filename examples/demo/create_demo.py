#!/usr/bin/env python3
"""Regenerate the entirely fictional, deterministic four-generation demo."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1] / "src"))
from genealogy.case import CaseStore, ResearchCase
from genealogy.models import (
    AccessLevel, Claim, ClaimStatus, Citation, Confidence, Event, Evidence,
    Finding, Hypothesis, Name, Person, Place, Relationship, ResearchQuestion,
    Source, Study, LivingStatus,
)

STAMP = "2026-01-01T00:00:00+00:00"
FIRST = ["Ada", "Bram", "Celia", "Dorian", "Elara", "Felix", "Greta", "Hugo", "Iris", "Jonas", "Kezia", "Luca", "Mara", "Nico", "Orla", "Pavel", "Rhea", "Silas", "Talia", "Ulric", "Vera", "Wes", "Xanthe", "Yorick", "Zella", "Arden", "Briony", "Cato", "Delia", "Emil", "Flora", "Galen", "Hester", "Ivo", "June", "Kellan", "Liora", "Milo", "Nessa", "Oren", "Petra", "Quill"]
SURNAMES = ["Alder", "Bell", "Cairn", "Dale", "Ember", "Firth", "Grove", "Hale"]

def build() -> ResearchCase:
    c = ResearchCase("demo", "The Alderwick Family | Fictional Research Case", "A fully invented four-generation family created to demonstrate people, relationships, places, citations, maps, timelines and research review. Every record is public and every person is deceased.", created_at=STAMP, updated_at=STAMP)
    access = AccessLevel.PUBLIC
    places = [Place("place:lantern", "Lanternford (fictional)", latitude=55.86, longitude=-4.25, sensitivity=access, precision="settlement"), Place("place:willow", "Willowmere (fictional)", latitude=55.95, longitude=-3.19, sensitivity=access, precision="settlement"), Place("place:reed", "Reedhaven (fictional)", latitude=56.12, longitude=-4.76, sensitivity=access, precision="parish")]
    for p in places: c.add(p)
    source_defs = [
        ("src:register", "The Lanternford Parish Register, 1750–1899 (invented)", "fictional parish register", "folio 14, entry 3"),
        ("src:returns", "Willowmere Household Returns, 1801–1891 (invented)", "fictional census transcript", "schedule 22, household 6"),
        ("src:letters", "Alderwick Family Letters (invented manuscript collection)", "fictional letter collection", "box 2, letter 7"),
    ]
    for sid, title, typ, _ in source_defs: c.add(Source(sid, title, typ, repository="Fictional Lanternford Archive", access_note="Invented teaching source; no real archive or record.", sensitivity=access))
    for sid, _, _, loc in source_defs: c.add(Citation("cite:"+sid.split(":")[1], sid, locator=loc, transcription="Illustrative invented source reference; no quotation from a real record.", sensitivity=access))
    # Two founder couples, eight children with spouses, sixteen grandchildren, six later descendants = 42.
    nodes=[]
    for i in range(42):
        gen = 0 if i < 4 else 1 if i < 20 else 2 if i < 36 else 3
        birth = [1754, 1780, 1810, 1841][gen] + (i % 7)
        death = min(1899, birth + 54 + (i % 29))
        name = f"{FIRST[i]} {SURNAMES[(i//2)%len(SURNAMES)]}"
        pid=f"person:{i+1:02d}"
        evb=f"event:{i+1:02d}:birth"; evd=f"event:{i+1:02d}:death"
        place=places[i%3]
        c.add(Event(evb,"birth",f"{birth}-01-01","year",place.id,[pid],sensitivity=access))
        c.add(Event(evd,"death",f"{death}-12-31","year",places[(i+1)%3].id,[pid],sensitivity=access))
        given, surname = name.split()
        c.add(Person(pid,[Name(name,"birth",confidence=Confidence.PROBABLE,given=given,surname=surname)],[evb,evd],living=LivingStatus.DECEASED,notes="Fictional person; dates and identity are illustrative.",sensitivity=access))
        nodes.append(dict(id=pid,name=name,birth=birth,death=death,place=place.name,placeid=place.id))
    # Evidence and sourced, explicitly graded relationship claims. A parent
    # relationship points from the child (subject) to the parent (object).
    for i in range(4,12):
        parent=(i-4)//4*2
        confidence=Confidence.PROBABLE if i==9 else Confidence.DOCUMENTED
        c.add(Relationship(f"rel:parent:{i+1}",nodes[i]["id"],nodes[parent]["id"],"parent",confidence,sensitivity=access))
        claimid=f"claim:parent:{i+1}"
        cit="cite:letters" if i==9 else "cite:register"
        c.add(Claim(claimid,nodes[i]["id"],"parent",nodes[parent]["name"], [cit],ClaimStatus.SUPPORTED,confidence,"Register entry names the household; one link remains probable because the matching given name is shared.",access))
        c.add(Evidence(f"evidence:parent:{i+1}",claimid,cit,"The invented source entry is described as naming this parent-child link.",True,confidence,access))
    for i in range(20,36):
        parent=4+(i-20)//2
        c.add(Relationship(f"rel:parent:{i+1}",nodes[i]["id"],nodes[parent]["id"],"parent",Confidence.DOCUMENTED,sensitivity=access))
    for i in range(36,42):
        parent=20+(i-36)
        confidence=Confidence.POSSIBLE if i==41 else Confidence.DOCUMENTED
        c.add(Relationship(f"rel:parent:{i+1}",nodes[i]["id"],nodes[parent]["id"],"parent",confidence,sensitivity=access))
    # Pair spouses among each adult generation; marriage dates are illustrative.
    for a,b,yr in [(0,1,1777),(2,3,1779),(4,12,1802),(5,13,1804),(6,14,1806),(7,15,1808),(8,16,1810),(9,17,1812),(10,18,1814),(11,19,1816)]:
        c.add(Relationship(f"rel:spouse:{a+1}:{b+1}",nodes[a]["id"],nodes[b]["id"],"spouse",Confidence.PROBABLE,sensitivity=access))
        c.add(Event(f"event:marriage:{a+1}:{b+1}","marriage",f"{yr}-06-01","year",places[(a+b)%3].id,[nodes[a]["id"],nodes[b]["id"]],"Invented ceremony date",sensitivity=access))
    c.add(Hypothesis("hypothesis:42", "Person 42 may be the child of Person 41; the supplied family sketch is suggestive but no independent matching entry is represented.",[nodes[40]["id"],nodes[41]["id"]],status="open",confidence=Confidence.POSSIBLE,sensitivity=access))
    c.add(ResearchQuestion("question:parentage", "Can the probable parent link for person 10 be distinguished from another same-named adult?",[nodes[8]["id"],nodes[9]["id"]],priority="high",sensitivity=access))
    c.add(ResearchQuestion("question:household", "Which invented household return best connects the Willowmere branch to Lanternford?",[nodes[10]["id"],nodes[18]["id"]],sensitivity=access,resolves="An invented household return naming both branches at one address."))
    c.add(Finding("finding:overview", "The demo models a 42-person, four-generation Alderwick family across three fictional locations; parentage is mostly documented in the invented evidence model, with two explicitly uncertain links.",[nodes[0]["id"],nodes[41]["id"]],["evidence:parent:5"],status="reviewed",confidence=Confidence.PROBABLE,sensitivity=access,recorded_on="2026-09-14"))
    c.add(Finding("finding:willowmere-household", "The invented Willowmere household return names Elara Cairn beside Mara Grove, consistent with their recorded marriage; it does not by itself prove which Cairn household she came from.",[nodes[4]["id"],nodes[12]["id"],"place:willow"],["evidence:parent:5"],status="draft",confidence=Confidence.POSSIBLE,sensitivity=access,recorded_on="2026-10-02"))
    c.add(Study("study:households", "Two households, one family: Lanternford and Willowmere",
        summary="How the invented Lanternford register and Willowmere returns connect Ada Alder's children to the Willowmere branch.",
        rationale="Several children share given names across the two places. This study sets out which records tie each child to Ada Alder and which links remain uncertain.",
        body="## What the records say\n\nThe invented register names [[person:05]] and her siblings in one household entry. The Willowmere return lists [[person:05|Elara]] with [[person:13]] after 1802.\n\n- **Documented:** the register entry for the four children of [[person:01]].\n- *Probable:* the link for person 10, because a second adult shares the given name.\n\n> Every source in this study is invented for demonstration.\n\n## Still to check\n\nWhether [[question:household]] can be answered from the household returns alone.",
        conclusion="The Lanternford children are documented as Ada Alder's; the Willowmere household is a probable continuation of Elara Cairn's line, pending [[finding:willowmere-household]].",
        related_ids=[nodes[0]["id"],nodes[4]["id"],nodes[12]["id"],"place:lantern","place:willow","src:register","src:returns","finding:overview","finding:willowmere-household","question:household"],
        status="draft",updated_on="2026-10-02",sensitivity=access))
    c.created_at=c.updated_at=STAMP
    return c

def write_inputs(nodes):
    inp=ROOT/"input"; inp.mkdir(parents=True,exist_ok=True)
    # GEDCOM with two founders + 4 child couples + 8 grandchild couples and 16 descendants.
    lines=["0 HEAD","1 SOUR Fictional Alderwick Demo","1 GEDC","2 VERS 5.5.1"]
    for index, n in enumerate(nodes):
        lines += [f"0 @{n['id']}@ INDI",f"1 NAME {n['name'].split()[0]} /{n['name'].split()[1]}/","1 BIRT",f"2 DATE 1 JAN {n['birth']}",f"2 PLAC {n['place']}","3 MAP",f"4 LATI {n['latitude']}",f"4 LONG {n['longitude']}",f"2 SOUR @S{index % 3 + 1}@",f"3 PAGE invented entry {index + 1}","1 DEAT",f"2 DATE 31 DEC {n['death']}",f"2 PLAC {n['place']}"]
    fam=1
    for i in range(4,12,4):
        parent=(i-4)//4*2
        lines += [f"0 @F{fam}@ FAM",f"1 HUSB @{nodes[parent]['id']}@",f"1 WIFE @{nodes[parent+1]['id']}@",*[f"1 CHIL @{nodes[j]['id']}@" for j in range(i,i+4)],"1 MARR","2 DATE 1 JUN 1800","2 PLAC Lanternford (fictional)"]
        fam+=1
    for i in range(20,36,2):
        parent=4+(i-20)//2
        lines += [f"0 @F{fam}@ FAM",f"1 HUSB @{nodes[parent]['id']}@",f"1 WIFE @{nodes[12+(parent-4)]['id']}@",f"1 CHIL @{nodes[i]['id']}@",f"1 CHIL @{nodes[i+1]['id']}@"]
        fam+=1
    for i in range(36,42,2):
        parent=20+(i-36)
        lines += [f"0 @F{fam}@ FAM",f"1 HUSB @{nodes[parent]['id']}@",f"1 CHIL @{nodes[i]['id']}@",f"1 CHIL @{nodes[i+1]['id']}@"]
        fam+=1
    for index, title in enumerate((
        "The Lanternford Parish Register (invented)",
        "Willowmere Household Returns (invented)",
        "Alderwick Family Letters (invented)",
    ), 1):
        lines += [f"0 @S{index}@ SOUR", f"1 TITL {title}", "1 REPO Fictional Lanternford Archive"]
    lines += ["0 TRLR"]
    (inp/"family.ged").write_text("\n".join(lines)+"\n",encoding="utf-8")
    people=[]
    for i,n in enumerate(nodes):
        row={"id":n["id"],"name":n["name"],"birth_date":f"{n['birth']}-01-01","death_date":f"{n['death']}-12-31","birth_place":n["place"],"birth_latitude":n["latitude"],"birth_longitude":n["longitude"],"death_place":n["place"],"Privacy":60,"living":False}
        if 4<=i<12:
            p=(i-4)//4*2
        elif 20<=i<36:
            p=4+(i-20)//2
        elif i>=36:
            p=20+(i-36)//2*2
        else:
            p=None
        if p is not None:
            row["father_id"]=nodes[p]["id"]; row["father_confidence"]="unknown"
        people.append(row)
    (inp/"one-tree.json").write_text(json.dumps({"people":people},indent=2)+"\n",encoding="utf-8")

def main():
    case=build()
    CaseStore(ROOT/"cases").save(case)
    nodes=[]
    for i,p in enumerate(case.records(Person)):
        events={e.id:e for e in case.records(Event)}
        birth=next(events[e] for e in p.event_ids if events[e].kind=="birth")
        death=next(events[e] for e in p.event_ids if events[e].kind=="death")
        pl={x.id:x for x in case.records(Place)}
        nodes.append(dict(id=p.id,name=p.names[0].value,birth=int(birth.date[:4]),death=int(death.date[:4]),place=pl[birth.place_id].name,placeid=birth.place_id,latitude=pl[birth.place_id].latitude,longitude=pl[birth.place_id].longitude))
    write_inputs(nodes)

if __name__ == "__main__": main()
