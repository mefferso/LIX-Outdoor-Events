# Event Sources

This application is an IDSS support layer, not an exhaustive entertainment calendar.

## Current MVP seed sources

The initial dataset contains a small set of manually verified events so the operational map can be evaluated before automated collection is enabled.

| Source | Role | Typical coverage |
|---|---|---|
| Audubon Nature Institute | authoritative organizer/venue | Audubon Zoo outdoor special events |
| LSU Athletics | authoritative athletics | major LSU home outdoor sports |
| NewOrleans.com | discovery / organizer-linked | major New Orleans festivals and public events |
| BlackAmericana Fest / ticket listing | organizer-linked | BlackAmericana Fest |
| L.O.C.A.L.S. Fest | organizer | Armstrong Park festival |

Every published seed record contains a source URL. Unknown attendance is not inferred.

## Planned automated registry

The approved source plan adds independent adapters for:

- New Orleans tourism/event calendars
- Visit Baton Rouge
- Louisiana Northshore
- Houma/Thibodaux
- Mississippi Gulf Coast
- LSU, Tulane, UNO, Southeastern Louisiana, Nicholls, and other major home athletics
- official city/parish, venue, race, parade, festival, park, and coastal/marine organizers

Automated discovery must preserve provenance and must not publish an event simply because it appears on a calendar. Outdoor exposure and IDSS relevance remain required gates.

See the approved design and implementation plan under `docs/superpowers/`.
