"""Viator-specific CSS / text selectors and marker lists."""

# ------------------------------------------------------------------ #
# Detail-URL slug pattern                                              #
# ------------------------------------------------------------------ #
# Viator tour URLs end with  /d<dest_id>-<alphanumeric_product_code>
# e.g.  /tours/Barcelona/Sagrada-Familia-Tour/d562-190179P1
# The last two segments are: <tour-slug>/<dest_id>-<product_code>
DETAIL_SLUG_PATTERN = r"/tours/[^/]+/[^/]+/d\d+-[A-Za-z0-9]+/?$"

# ------------------------------------------------------------------ #
# "Check Availability" button labels (EN + ES)                        #
# ------------------------------------------------------------------ #
CHECK_AVAILABILITY_LABELS = [
    "Check Availability",
    "Comprobar disponibilidad",
    "Ver disponibilidad",
    "Check availability",
]

# ------------------------------------------------------------------ #
# Option / package card selectors (tried in order)                    #
# ------------------------------------------------------------------ #
OPTION_CARD_SELS = (
    # Viator redesign (2024-2025)
    "[data-testid='product-card']",
    "[data-testid='option-card']",
    "[data-testid='availability-option']",
    # Older selectors still sometimes present
    ".option-card",
    ".availability-option",
    # Radio-based picker (3rd screenshot layout)
    "[data-testid='product-option-radio']",
    "label[data-testid*='option']",
    # Generic fallback: anything holding a price inside the booking widget
    ".booking-section [role='radio']",
    ".product-options [role='radio']",
    # Broad fallback
    "[class*='ProductCard']",
    "[class*='OptionCard']",
    "[class*='availabilityOption']",
)

# Time-slot button selectors (inside expanded option)
TIME_SLOT_SELS = (
    "[data-testid*='time-slot']",
    "[data-testid*='timeslot']",
    "button[aria-label*='AM']",
    "button[aria-label*='PM']",
    "[class*='TimeSlot']",
    "[class*='timeSlot']",
    "[class*='time-slot']",
)

# Booking widget / availability panel wrapper selectors
BOOKING_WIDGET_SELS = (
    "[data-testid='booking-widget']",
    "[data-testid='availability-panel']",
    "#booking-section",
    ".booking-widget",
    "[class*='BookingWidget']",
    "[class*='bookingWidget']",
)

# ------------------------------------------------------------------ #
# Text markers that indicate a slot / option is unavailable           #
# ------------------------------------------------------------------ #
UNAVAILABLE_MARKERS = [
    "sold out",
    "no availability",
    "unavailable",
    "not available",
    "agotado",
    "sin disponibilidad",
    "no disponible",
    "no hay plazas",
]
