# Data Model

Both `dubai_cars.json` and `apartments.json` are flat arrays of records. Use them directly; no schema migrations needed.

## Cars — `Car Search - Dubai UAE/dubai_cars.json`

```jsonc
{
  "source": "Dubizzle",                       // "Dubizzle" | "DubiCars" | "YallaMotor"
  "ad_id": "dubizzle_<uuid>",                 // unique key
  "title": "Honda Civic | 177k KM | ...",     // seller's title
  "brand": "Honda Civic",                     // canonical brand+model
  "year": 2014,                               // int or null
  "km": 177000,                               // int or null (odometer)
  "price_aed": 18500,                         // int (total AED)
  "transmission": "Automatic",                // free text
  "trim": "LXi",                              // free text
  "color": "Beige",
  "body_type": "Sedan",
  "fuel": "Petrol",
  "seller_type": "OW",                        // "OW" owner, "DL" dealer, "" unknown
  "location": "UAE > Dubai > Deira > ...",    // breadcrumb (Dubai-only after filter)
  "has_sunroof": true,                        // ← the flagship boolean
  "features": ["Air Conditioning", ...],      // [] when not enriched
  "description": "...",                       // detail-page text snippet
  "image": "https://...jpeg",                 // CDN URL or ""
  "url": "https://dubai.dubizzle.com/...",    // listing page
  "scraped_at": "2026-05-17T14:32:11",
  "score": 73.4,                              // 0-100 composite (see prep_data.py)
  "sub_scores": {                             // 8 components, each 0-100
    "price": 100, "mileage": 65, "age": 70,
    "reliability": 85, "kpy": 80, "value": 90,
    "transmission": 80, "sunroof": 100
  },
  "rating": "GOOD"                            // "EXCELLENT"|"GOOD"|"FAIR"|"BELOW AVG"|"POOR"
}
```

### Cars: sort + filter conventions

- Sort: `sunroof_then_score` (default), `price_asc`, `price_desc`, `year_desc`, `km_asc`, `score`.
- Hard filter: Dubai-only (we drop everything else in `merge_dedupe`).
- Frontend cap: max price 30K AED. Bot will filter by `max_price` user-specified.

## Apartments — `Apartment Search - Dubai/apartments.json`

```jsonc
{
  "source": "Bayut",                           // "Bayut" | "PropertyFinder"
  "ad_id": "bayut_<externalID>",
  "title": "Spacious Furnished 1BHK ...",
  "price_aed": 55000,                          // YEARLY total AED
  "monthly_aed": 4583,                         // = price_aed / 12, pre-rounded
  "bedrooms": 1,                               // always 1 (filter)
  "bathrooms": 1,                              // int or null
  "size_sqft": 480,                            // int or null
  "area": "Deira",                             // canonical short label
  "commute_tier": 2,                           // 1 (DAFZA-adjacent) – 4 (far)
  "full_location": "Deira, Al Khabaisi",       // breadcrumb
  "furnished": true,                           // always true (filter)
  "amenities": ["Parking","Gym","..."],
  "image": "https://images.bayut.com/thumbnails/<id>-800x600.jpeg",
  "url": "https://www.bayut.com/property/details-<externalID>.html",
  "broker": "Mira International",
  "agent_name": "Tamara Getigezheva",
  "agent_phone": "+971...",
  "lat": 25.27,
  "lon": 55.32,
  "description": "...",
  "scraped_at": "2026-05-17T14:32:11",
  // Added by prep_data.py:
  "tier_name": "DAFZA-adjacent",
  "score": 72.4,
  "sub_scores": {
    "commute": 100, "budget": 80, "size": 75,
    "amenities": 60, "bathrooms": 70, "image": 100
  },
  "rating": "GOOD",
  "within_budget": true
}
```

### Apartment commute tiers (Green Line + Red Line transfer)

| Tier | Time to DAFZA | Areas |
|---|---|---|
| 1 | 5–10 min walk/metro | Al Qusais, Al Twar, Hor Al Anz, DAFZA itself |
| 2 | 10–15 min | Deira, Al Garhoud, Al Rashidiya, Al Rigga, Naif |
| 3 | 15–20 min | Mirdif, Dubai Festival City, Al Nahda (Dubai), Stadium, Abu Hail, Al Muraqqabat |
| 4 | 20–30 min | Al Nahda Sharjah, Dubai Silicon Oasis, Al Mamzar |

## Stats — `window.CAR_STATS` / `window.APT_STATS`

```jsonc
// CAR_STATS
{
  "generated_at": "2026-05-17T14:32:11",
  "total": 65,
  "sunroof_count": 12,
  "by_brand":  { "Honda Civic": 16, ... },
  "by_source": { "Dubizzle": 43, "DubiCars": 22 }
}

// APT_STATS
{
  "generated_at": "2026-05-17T14:35:02",
  "total": 12,
  "within_budget": 12,
  "by_tier": { "1": 1, "2": 8, "3": 2, "4": 1 },
  "by_area": { "Al Qusais": 1, "Deira": 8, ... },
  "by_source": { "Bayut": 12 },
  "monthly_budget": 6000,
  "year_budget": 72000,
  "cheapest": { "monthly_aed": 4500, "area": "DSO", "tier": 4 }
}
```

## Versioning

- No schema versions. Both scrapers are idempotent and forward-compatible (new fields added; old fields preserved).
- If a field is missing on a record, frontends and bot tools default it gracefully (`null`, `0`, `""`).
- CSV exports flatten `amenities` / `features` into pipe-separated strings.
