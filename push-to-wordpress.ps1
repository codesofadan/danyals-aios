# =============================================================================
# push-to-wordpress.ps1
# One-shot publisher: pushes the AI-agents article to spotino.org through the
# AIOS Publisher plugin's own endpoint (no AIOS backend required).
#
# PREREQUISITES on the WordPress side:
#   1. Install + activate the AIOS Publisher plugin (aios-publisher.zip).
#   2. wp-admin -> AIOS Publisher -> Settings: copy the API Key below.
#   3. (Recommended) Install + activate Yoast SEO and the Spotino theme.
#
# Then fill in $ApiKey, and run:   pwsh ./push-to-wordpress.ps1
# The post is created as a DRAFT; publish it from wp-admin -> AIOS Content
# (or set $Status = "publish" below to go live immediately).
# =============================================================================

# ---- EDIT THESE ----------------------------------------------------------------
$Endpoint = "https://spotino.org/wp-json/aios/v1/publish"
$ApiKey   = "PASTE_YOUR_AIOS_PUBLISHER_KEY_HERE"
$Status   = "draft"          # "draft" (review first) or "publish" (go live now)
$FeaturedImageUrl = ""       # optional: a public image URL to set as the hero
# --------------------------------------------------------------------------------

$ContentFile = Join-Path $PSScriptRoot "best-ai-agents-for-seo-agencies-2026.html"
if (-not (Test-Path $ContentFile)) { Write-Error "Content file not found: $ContentFile"; exit 1 }
if ($ApiKey -eq "PASTE_YOUR_AIOS_PUBLISHER_KEY_HERE" -or [string]::IsNullOrWhiteSpace($ApiKey)) {
	Write-Error "Set `$ApiKey to your AIOS Publisher key (wp-admin -> AIOS Publisher -> Settings)."; exit 1
}

$Title = "Best AI Agents for SEO Agencies in 2026"
$Slug  = "best-ai-agents-for-seo-agencies-in-2026"
$MetaTitle = "Best AI Agents for SEO Agencies in 2026 | Tools, GEO & Stack Guide"
$MetaDescription = "The best AI agents for SEO agencies in 2026 — agentic platforms, content optimization, GEO/AI-search visibility, technical audits and how to stack them without risking client sites."
$FocusKeyword = "AI agents for SEO agencies"
$Content = Get-Content $ContentFile -Raw

# Article (BlogPosting) JSON-LD. Yoast also emits schema; the plugin adds this
# for the article + FAQ. Harmless to have both — search engines de-dupe by @type.
$today = (Get-Date).ToString("yyyy-MM-dd")
$schema = @{
	"@context" = "https://schema.org"
	"@graph"   = @(
		@{
			"@type"            = "BlogPosting"
			"headline"         = $Title
			"description"      = $MetaDescription
			"datePublished"    = $today
			"dateModified"     = $today
			"mainEntityOfPage" = "https://spotino.org/$Slug"
			"author"           = @{ "@type" = "Organization"; "name" = "Spotino" }
			"publisher"        = @{ "@type" = "Organization"; "name" = "Spotino" }
		}
	)
} | ConvertTo-Json -Depth 8 -Compress

$payload = @{
	api_key          = $ApiKey
	title            = $Title
	slug             = $Slug
	content          = $Content
	status           = $Status
	post_type        = "post"
	meta_title       = $MetaTitle
	meta_description = $MetaDescription
	focus_keyword    = $FocusKeyword
	categories       = @("SEO")
	schema_jsonld    = $schema
}
if (-not [string]::IsNullOrWhiteSpace($FeaturedImageUrl)) {
	$payload.featured_image_url = $FeaturedImageUrl
}

$json = $payload | ConvertTo-Json -Depth 10

Write-Host "Pushing '$Title' to $Endpoint ..." -ForegroundColor Cyan
try {
	$resp = Invoke-RestMethod -Uri $Endpoint -Method Post -Body $json -ContentType "application/json" `
		-Headers @{ "X-AIOS-Key" = $ApiKey } -TimeoutSec 60
} catch {
	Write-Error "Push failed: $($_.Exception.Message)"
	if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message }
	exit 1
}

if ($resp.ok) {
	Write-Host "`nSUCCESS" -ForegroundColor Green
	Write-Host ("Post ID  : {0}" -f $resp.post_id)
	Write-Host ("Status   : {0}" -f $resp.status)
	Write-Host ("Live URL : {0}" -f $resp.url)
	Write-Host ("Edit URL : {0}" -f $resp.edit_url)
	if ($Status -eq "draft") {
		Write-Host "`nIt's a DRAFT. Publish it from wp-admin -> AIOS Content, or set `$Status='publish' and re-run." -ForegroundColor Yellow
	}
} else {
	Write-Host "Unexpected response:" -ForegroundColor Yellow
	$resp | ConvertTo-Json -Depth 6
}
