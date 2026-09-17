# Schema.org LocalBusiness - operational reference

Loaded by: B4 (Schema), D1 (GBP), D4 (Local Pack + Geo).
Source: schema.org/LocalBusiness + Google Rich Results docs for local business.

## Hierarchy

`Thing > Place > LocalBusiness`

Subtypes that inherit LocalBusiness properties (use the most specific one):
- Plumber, Electrician, RoofingContractor, HVACBusiness, LegalService, Attorney, Dentist, Physician, MedicalBusiness, AutoRepair, RealEstateAgent, BeautySalon, HairSalon, GeneralContractor, ChildCare, FoodEstablishment, Restaurant, Bakery, BarOrPub, CafeOrCoffeeShop, Store, ClothingStore, HardwareStore, GroceryStore, FurnitureStore.

When in doubt, default to LocalBusiness; refining to a subtype is always better.

## Required properties for rich results

The minimum set Google requires for local business rich results:

| Property | Type | Notes |
|---|---|---|
| @type | string | Use the most specific subtype |
| name | string | Business name as on GBP |
| address | PostalAddress | All five address fields below |
| telephone | string | International format preferred |

## Address - required sub-properties

```json
"address": {
  "@type": "PostalAddress",
  "streetAddress": "Main Boulevard 12",
  "addressLocality": "Lahore",
  "addressRegion": "Punjab",
  "postalCode": "54000",
  "addressCountry": "PK"
}
```

All five must be present for rich result eligibility.

## Strongly recommended properties

| Property | Type | Why |
|---|---|---|
| url | URL | Canonical site URL |
| image | URL | Photo of business, exterior preferred |
| priceRange | string | "$", "$$", "$$$", "$$$$" |
| geo | GeoCoordinates | latitude + longitude |
| openingHoursSpecification | OpeningHoursSpecification[] | weekday + open/close |
| areaServed | Place or string | service area for service businesses |
| sameAs | URL[] | links to GBP, Yelp, Facebook, Wikidata |
| aggregateRating | AggregateRating | only if reviews are on-site |

## Common errors B4 catches

- `address` is a plain string, not a PostalAddress object
- Missing `addressCountry`
- `telephone` formatted inconsistently with GBP
- `openingHoursSpecification` uses old `openingHours` string format
- `sameAs` missing the GBP URL
- `aggregateRating` present without any actual reviews on the page (Google policy violation)

## Multi-location pattern

For businesses with multiple locations:
- One LocalBusiness block per location, on its location page
- `@id` URL fragment per location for graph linking
- The parent Organization links to all locations via `branchOf` or `parentOrganization`

## How B4 emits findings using this

B4 cites the specific missing property and supplies a corrected JSON-LD snippet. "LocalBusiness block missing addressCountry; rich result ineligible. Corrected snippet below. Add Plumber as the @type subtype to win the plumbing-specific rich result."
