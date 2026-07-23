-- 0046_directories_seed.sql - seeds public.directories (0045) with the full
-- citation-directory catalog from the 17 Jul 2026 agency reference (155 sites
-- across 4 markets + the data-aggregator/global-API layer). Idempotent
-- (on conflict (name, market) do nothing) so re-running this file after an
-- edit never duplicates rows; editing a site's tier/pricing going forward is a
-- new migration that UPDATEs by (name, market), not a hand-edit of this seed.
--
-- tier is the same automation vocabulary the reference plan tags every site
-- with: aggregator (push once, fans out downstream - or fed BY another
-- aggregator, needing no separate action) / api (a documented, self-serve write
-- API) / bot_fillable (a plain web form our Playwright bot fills, no CAPTCHA) /
-- captcha_assisted (the same, gated by a CAPTCHA our solver + a human spotcheck
-- clear) / manual_only (no automatable path at all - kept in the catalog for
-- completeness/reporting; a worker never claims one of these rows).
--
-- price_note/automation_note are DELIBERATELY short (a phrase, not the source
-- document's full paragraph) - this is an operational catalog a submission
-- worker reads, not the client-facing reference doc. Re-verify pricing/API
-- status against the live source before it drives a paid decision (the
-- reference doc's own "note on promises" applies here too).

insert into public.directories
  (name, url, market, tier, submit_method, link_rel, price_note, automation_note)
values

-- --- Data aggregators & global API platforms (15, mostly GLOBAL) ---------------
('Data Axle (Local Listings)', 'data-axle.com', 'GLOBAL', 'aggregator', 'aggregator:data_axle', 'unknown', '~$30/location managed', 'Phone verification before distribution; no public write API'),
('Foursquare Places', 'foursquare.com', 'GLOBAL', 'api', 'api:foursquare_places', 'unknown', '500 calls/mo free, then ~$0.019/call', 'Real Places API; highest-leverage single integration'),
('TransUnion / Neustar (Localeze)', 'neustarlocaleze.biz', 'GLOBAL', 'manual_only', 'manual', 'unknown', '~$79/yr for 1-24 locations', 'Portal-only signup, no public API'),
('Bing Places for Business', 'bingplaces.com', 'GLOBAL', 'api', 'api:bing_places', 'nofollow', 'Free', 'Real API + bulk Excel upload to 10k locations; single listings need phone/email verify'),
('Apple Business Connect', 'businessconnect.apple.com', 'GLOBAL', 'captcha_assisted', 'bot:playwright+captcha', 'unknown', 'Free', 'API exists but net-new listings are identity-verification gated'),
('Facebook Business (Page)', 'facebook.com/business', 'GLOBAL', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free', 'Graph API manages an existing Page; net-new Page creation trips anti-bot checkpoints'),
('Yelp', 'yelp.com', 'GLOBAL', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free to claim', 'No create/claim API; phone-call verification code gates the claim'),
('OpenStreetMap', 'openstreetmap.org', 'GLOBAL', 'manual_only', 'manual', 'unknown', 'Free', 'A real OAuth editing API exists, but community norms explicitly forbid bulk/automated POI inserts (ban/revert risk) - catalogued manual_only despite the API, never auto-dispatched'),
('HERE', 'here.com', 'GLOBAL', 'aggregator', 'aggregator:fed_by_data_axle_neustar', 'unknown', 'Free', 'Fed by the core aggregators; no separate action needed'),
('TomTom', 'tomtom.com', 'GLOBAL', 'aggregator', 'aggregator:fed_by_data_axle_foursquare', 'unknown', 'Free', 'Fed by the core aggregators; no separate action needed'),
('Waze', 'waze.com', 'GLOBAL', 'aggregator', 'aggregator:fed_by_data_axle_foursquare', 'unknown', 'Free', 'Fed by the core aggregators; a free manual Map Editor also exists'),
('Yahoo Local', 'local.yahoo.com', 'GLOBAL', 'aggregator', 'aggregator:fed_by_data_axle_foursquare', 'unknown', 'Free', 'No direct submission; covered by the aggregators'),
('MapQuest', 'mapquest.com', 'GLOBAL', 'aggregator', 'aggregator:fed_by_data_axle_foursquare', 'unknown', 'Free', 'No direct submission; covered by the aggregators'),
('Superpages / YP Network (Thryv)', 'superpages.com', 'GLOBAL', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing; paid upsells', 'One claim covers Superpages/DexKnows/YellowBook'),
('Factual', 'factual.com', 'GLOBAL', 'aggregator', 'aggregator:fed_by_foursquare', 'unknown', 'n/a', 'Merged into Foursquare (2020); seeding Foursquare covers it'),

-- --- United States - general directories (33) -----------------------------------
('YellowPages.com', 'yellowpages.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free basic; paid ad tiers', 'Verification gates the claim'),
('Manta', 'manta.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free; paid upgrades', 'Email verification; confirm CAPTCHA on the live form'),
('MerchantCircle', 'merchantcircle.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free; paid upsells', 'Bot-fillable add-listing form'),
('Chamber of Commerce', 'chamberofcommerce.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'Bot-fillable; distinct from local chamber membership'),
('Hotfrog', 'hotfrog.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'Thryv network; country variants exist'),
('Brownbook', 'brownbook.net', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Openly editable, historically low-friction'),
('Cylex USA', 'cylex-usa.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free; paid upgrades', 'Mini-aggregator to partner directories'),
('EZLocal', 'ezlocal.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + paid tier', 'Bot-fillable add-listing form'),
('ShowMeLocal', 'showmelocal.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Country variants exist'),
('Tupalo', 'tupalo.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Also propagated via aggregator networks'),
('CitySquares', 'citysquares.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + account', 'Mid-tier local directory'),
('YaSabe', 'yasabe.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Hispanic-market-leaning directory'),
('Judy''s Book', 'judysbook.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + account', 'Local reviews + listings'),
('YellowBot', 'yellowbot.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + account', 'Mid-tier directory'),
('n49', 'n49.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Canada-born, serves US too'),
('Opendi', 'opendi.us', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Low authority; country variants exist'),
('Tuugo', 'tuugo.us', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Low authority; global variants'),
('MyHuckleberry', 'myhuckleberry.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + account', 'Mid/low authority'),
('Storeboard', 'storeboard.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + account', 'Business social network + listings'),
('Infobel', 'infobel.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Global directory with country sections'),
('Cybo', 'cybo.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Global business directory'),
('Apsense', 'apsense.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + account', 'Business social network profile'),
('Callupcontact', 'callupcontact.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Low/mid authority'),
('Kompass', 'kompass.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free basic + paid', 'B2B directory; moderated before listing'),
('EnrollBusiness', 'enrollbusiness.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Country variants exist'),
('Yellow.place', 'yellow.place', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Global directory; low authority'),
('AGreaterTown', 'agreatertown.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Low authority'),
('FindIt', 'findit.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + account', 'Social + listing platform'),
('Nextdoor', 'nextdoor.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free business page', 'Address verification (postcard/phone) is a hard gate'),
('Trustpilot', 'trustpilot.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free business account', 'Domain/email verification required'),
('Better Business Bureau (BBB)', 'bbb.org', 'US', 'manual_only', 'manual', 'nofollow', 'Free basic; paid accreditation', 'Manual application + human review'),
('Dun & Bradstreet (D&B)', 'dnb.com', 'US', 'manual_only', 'manual', 'unknown', 'Free D-U-N-S request', 'Multi-day identity/business verification, not a quick citation'),
('Crunchbase', 'crunchbase.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free profile; paid Pro', 'New company profiles are moderated before going live'),

-- --- United States - niche / vertical directories (33) --------------------------
('Justia (Lawyers)', 'lawyers.justia.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free profile; paid upgrades', 'One of the more automatable legal directories'),
('FindLaw', 'findlaw.com', 'US', 'manual_only', 'manual', 'nofollow', 'Paid (Internet Brands)', 'Sales-rep onboarding only'),
('Martindale-Hubbell', 'martindale.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free claim + paid tiers', 'Identity/peer-review verification gate'),
('Avvo', 'avvo.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free (auto-built profile)', 'Profile likely already exists; claim is verification-gated'),
('Super Lawyers', 'superlawyers.com', 'US', 'manual_only', 'manual', 'nofollow', 'Selection-based', 'Editorial peer-nomination; not self-submittable'),
('HG.org', 'hg.org', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free/paid web form', 'Automatable legal/general directory'),
('Nolo / Lawyers.com', 'nolo.com', 'US', 'manual_only', 'manual', 'nofollow', 'Paid Martindale-Nolo program', 'No free self-serve citation'),
('Healthgrades', 'healthgrades.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free (auto-generated from NPI)', 'Provider profile likely exists; claim is verification-gated'),
('Zocdoc', 'zocdoc.com', 'US', 'manual_only', 'manual', 'nofollow', 'Paid SaaS', 'Paid provider onboarding; not a citation to automate'),
('WebMD / Vitals', 'webmd.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free profile (Vitals network)', 'Claim requires NPI/identity verification'),
('RateMDs', 'ratemds.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free (auto-listed); paid upgrades', 'Auto-listed; claim + verification'),
('Wellness.com', 'wellness.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'One of the more automatable health directories'),
('Psychology Today', 'psychologytoday.com', 'US', 'manual_only', 'manual', 'nofollow', 'Paid (~$30/mo)', 'Paid + therapist license verification'),
('FindaTopDoc', 'findatopdoc.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free profile', 'Automatable mid-tier medical directory'),
('Houzz', 'houzz.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free pro profile; paid ads', 'Relatively low-friction signup'),
('Angi (Angie''s List)', 'angi.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free basic; paid leads', 'Phone verification; lead-gen model'),
('HomeAdvisor', 'homeadvisor.com', 'US', 'manual_only', 'manual', 'nofollow', 'Paid membership + screening', 'Background check + payment; Angi network'),
('Thumbtack', 'thumbtack.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free profile; pay per lead', 'Phone/identity verification to activate'),
('Porch', 'porch.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free profile; paid leads', 'Pro signup + verification'),
('BuildZoom', 'buildzoom.com', 'US', 'aggregator', 'aggregator:contractor_license_autogen', 'nofollow', 'Free (auto-created)', 'Profiles auto-created from public contractor-license records'),
('HomeStars', 'homestars.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'Strong in Canada; also automatable in the US'),
('The Blue Book', 'thebluebook.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free commercial-construction listing', 'Commercial construction niche'),
('TripAdvisor', 'tripadvisor.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free listing; paid ads', 'Owner verification (email/phone/postcard) to manage'),
('OpenTable', 'opentable.com', 'US', 'manual_only', 'manual', 'nofollow', 'Paid SaaS + hardware', 'Contract + hardware onboarding'),
('Zomato', 'zomato.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing/claim', 'US footprint reduced; verify relevance per client'),
('MenuPix', 'menupix.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Automatable restaurant directory'),
('Allmenus / Restaurantji', 'allmenus.com', 'US', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Restaurantji is aggregator-fed; Allmenus is a menu form'),
('Grubhub', 'grubhub.com', 'US', 'manual_only', 'manual', 'nofollow', 'Paid merchant (commission)', 'Onboarding + banking verification'),
('Zillow', 'zillow.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free agent profile; paid leads', 'Identity/phone verification gates the profile'),
('Realtor.com', 'realtor.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free agent profile; paid leads', 'NAR/identity verification'),
('Trulia', 'trulia.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free agent profile', 'Zillow Group; shares the same verification path'),
('Cars.com / CarGurus', 'cars.com', 'US', 'manual_only', 'manual', 'nofollow', 'Paid dealer subscription', 'Sales-gated subscription + feed'),
('DealerRater', 'dealerrater.com', 'US', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free dealer claim', 'Email verification; reviews-focused'),

-- --- United Kingdom - directories (25) -------------------------------------------
('Yell', 'yell.com', 'UK', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free listing; paid ad packages', 'Primary UK directory (former Yellow Pages UK)'),
('Thomson Local', 'thomsonlocal.com', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing; paid upgrades', 'Established UK directory'),
('Scoot', 'scoot.co.uk', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'Part of a UK directory network'),
('FreeIndex', 'freeindex.co.uk', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'Popular free UK directory'),
('Cylex UK', 'cylex-uk.co.uk', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free (paid upgrades)', 'Mini-aggregator behaviour'),
('Hotfrog UK', 'hotfrog.co.uk', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'Thryv network UK edition'),
('Yelp UK', 'yelp.co.uk', 'UK', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free claim; paid ads', 'Same Yelp verification model as US'),
('192.com', '192.com', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'Directory + people-search hybrid'),
('Kompass UK', 'gb.kompass.com', 'UK', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free basic + paid', 'B2B; moderated'),
('Brownbook (UK)', 'brownbook.net', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Global directory serving UK'),
('Checkatrade', 'checkatrade.com', 'UK', 'manual_only', 'manual', 'nofollow', 'Paid membership + vetting', 'Background-vetted trades directory'),
('Bark', 'bark.com', 'UK', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free profile; pay per lead', 'Lead-gen signup'),
('RatedPeople', 'ratedpeople.com', 'UK', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Paid leads', 'Trade signup + verification'),
('Applegate', 'applegate.co.uk', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + paid', 'B2B/industrial directory'),
('Yalwa UK', 'yalwa.co.uk', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Low authority'),
('Bizwiki UK', 'bizwiki.co.uk', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Mid/low authority'),
('Opendi UK', 'opendi.co.uk', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Low authority; global network'),
('Misterwhat UK', 'misterwhat.co.uk', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Low authority'),
('UK Small Business Directory', 'uksmallbusinessdirectory.co.uk', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + paid', 'SMB-focused'),
('Thebestof', 'thebestof.co.uk', 'UK', 'manual_only', 'manual', 'nofollow', 'Paid membership', 'Paid local network'),
('Europages UK', 'europages.co.uk', 'UK', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free basic + paid', 'Pan-European B2B directory'),
('2FindLocal (UK)', '2findlocal.com', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Global/local directory'),
('Businessmagnet', 'businessmagnet.co.uk', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + paid', 'B2B directory'),
('TouchLocal', 'touchlocal.com', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + paid', 'UK local directory'),
('Reach plc regional network', 'liverpoolecho.co.uk', 'UK', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'One shared platform behind many high-DA regional titles'),

-- --- Canada - directories (26) ---------------------------------------------------
('YellowPages.ca', 'yellowpages.ca', 'CA', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free basic; paid ads', 'Highest-value Canadian citation'),
('Canada411', 'canada411.ca', 'CA', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free (YP-owned)', 'Covered largely by the YellowPages.ca listing'),
('411.ca', '411.ca', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'Independent CA local search'),
('n49 (Canada)', 'n49.com', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Canada-born listings + reviews'),
('Cylex Canada', 'cylex-canada.ca', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free (paid upgrades)', 'Syndicates to partner directories'),
('Hotfrog Canada', 'hotfrog.ca', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'Thryv network CA edition'),
('Ourbis', 'ourbis.ca', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + paid', 'Quebec/CA; Yellow Pages Group affiliate'),
('ProfileCanada', 'profilecanada.com', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + paid tiers', 'Canadian B2B directory'),
('Canadian Business Directory', 'canadianbusinessdirectory.ca', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'CA-only directory'),
('GoldBook.ca', 'goldbook.ca', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'CA business directory'),
('Weblocal.ca', 'weblocal.ca', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'CA local search + reviews'),
('Ziplocal', 'ziplocal.ca', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + paid', 'Toronto-based CA local-search network'),
('Findit (Canada)', 'findit.com', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + account', 'US social + listing platform accepting CA'),
('ChamberofCommerce.com (CA)', 'canada.chamberofcommerce.com', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'Large open CA/US directory'),
('Websites.ca', 'websites.ca', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + paid', 'CA directory network'),
('Infobel Canada', 'infobel.com/en/canada', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Global directory, CA section'),
('Brownbook (Canada)', 'brownbook.net', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Global open directory serving CA'),
('Cybo (Canada)', 'cybo.com', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Global directory'),
('Tupalo (Canada)', 'tupalo.com', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Social local reviews/listings'),
('Opendi.ca', 'opendi.ca', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Global network, CA domain'),
('CanadaOne', 'canadaone.com', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'CA small-business directory'),
('2FindLocal (Canada)', '2findlocal.com/en/ca', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Global/CA local directory'),
('FindHere.ca', 'findhere.ca', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'CA local directory'),
('Fyple.ca', 'fyple.ca', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'CA business directory'),
('MySheriff.ca', 'mysheriff.ca', 'CA', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'CA business directory'),
('BBB Canada', 'bbb.org', 'CA', 'manual_only', 'manual', 'nofollow', 'Free basic; paid accreditation', 'Manual, not automatable'),

-- --- Australia - directories (23) -------------------------------------------------
('True Local', 'truelocal.com.au', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing; paid ads', 'Major AU directory'),
('Yellow Pages Australia', 'yellowpages.com.au', 'AU', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free basic; paid ads', 'High-value AU citation (Sensis)'),
('White Pages Australia', 'whitepages.com.au', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'Sensis-owned'),
('StartLocal', 'startlocal.com.au', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'Popular free AU directory'),
('Hotfrog Australia', 'hotfrog.com.au', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'Thryv network AU edition'),
('Aussie Web', 'aussieweb.com.au', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + paid', 'One of Australia''s oldest directories'),
('Local Search', 'localsearch.com.au', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free basic; paid ads', 'Established AU local-search network'),
('Yelp Australia', 'yelp.com.au', 'AU', 'captcha_assisted', 'bot:playwright+captcha', 'nofollow', 'Free claim; paid ads', 'Same Yelp verification model'),
('Cylex Australia', 'cylex.com.au', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free (paid upgrades)', 'AU edition of Cylex'),
('Womo', 'womo.com.au', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'Word-of-mouth reviews directory'),
('Yalwa Australia', 'yalwa.com.au', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Low authority'),
('dLook', 'dlook.com.au', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + paid', 'AU business directory'),
('Fyple Australia', 'fyple.biz', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Low authority'),
('Local.com.au', 'local.com.au', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free listing', 'AU local directory'),
('ShowMeLocal Australia', 'au.showmelocal.com', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'AU edition'),
('Street Directory', 'street-directory.com.au', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free + paid', 'Mapping + directory hybrid'),
('Superpages Australia', 'superpages.com.au', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Low authority AU'),
('2FindLocal (Australia)', '2findlocal.com', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Global/local directory'),
('Tuugo (Australia)', 'tuugo.biz', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Global network'),
('Where Is', 'whereis.com', 'AU', 'captcha_assisted', 'bot:playwright+captcha', 'unknown', 'Free', 'Mapping/directory hybrid (Telstra-linked)'),
('Sensis', 'sensis.com.au', 'AU', 'manual_only', 'manual', 'unknown', 'Corporate parent', 'List via Yellow/White Pages instead'),
('Business Listings AU', 'businesslistings.net.au', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'AU business directory'),
('National Directory AU', 'nationaldirectory.com.au', 'AU', 'bot_fillable', 'bot:playwright', 'nofollow', 'Free', 'Low authority AU')

on conflict (name, market) do nothing;
