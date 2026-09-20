// ---------- Dietary policies (Action::"purchase_item") ----------
// They look at context.beneficiary: the member the item is FOR. "Dadi ke liye namkeen" ordered by Didi is
// checked against Dadi's profile. {for} is the beneficiary's name, {allergens} the matching allergens.

@id("diet-vegetarian")
@reason("{for} is vegetarian; this product is not vegetarian.")
@hinglish("{for} vegetarian hain, yeh item veg nahi hai.")
forbid (principal, action == Action::"purchase_item", resource)
when { resource.is_food && !resource.veg && ["veg", "jain"].contains(context.beneficiary.diet_profile) };

@id("diet-eggetarian")
@reason("{for} eats eggs but no other non-veg food; this product is not vegetarian.")
@hinglish("{for} sirf anda khate hain, yeh item non-veg hai.")
forbid (principal, action == Action::"purchase_item", resource)
when {
  resource.is_food && !resource.veg && !resource.eggetarian_only &&
  context.beneficiary.diet_profile == "eggetarian"
};

@id("diet-vegan")
@reason("{for} is vegan; this product has dairy, egg or honey.")
@hinglish("{for} vegan hain, is item mein doodh, anda ya shahad hai.")
forbid (principal, action == Action::"purchase_item", resource)
when { resource.is_food && !resource.vegan && context.beneficiary.diet_profile == "vegan" };

@id("diet-jain")
@reason("{for} is Jain; this product has onion, garlic or root vegetables.")
@hinglish("{for} Jain hain, is item mein pyaaz, lehsun ya jadwali sabzi hai.")
forbid (principal, action == Action::"purchase_item", resource)
when { resource.is_food && !resource.jain_friendly && context.beneficiary.diet_profile == "jain" };

@id("allergy")
@reason("{for} is allergic to {allergens}; this product contains it.")
@hinglish("{for} ko {allergens} se allergy hai, yeh item nahi de sakte.")
forbid (principal, action == Action::"purchase_item", resource)
when { resource.allergens.containsAny(context.beneficiary.allergies) };

@id("vrat-mode")
@reason("{for} is fasting (vrat) until {vrat_until}; only vrat-friendly food is allowed.")
@hinglish("{for} ka vrat {vrat_until} tak hai, sirf vrat ka khana order ho sakta hai.")
forbid (principal, action == Action::"purchase_item", resource)
when {
  resource.is_food && !resource.vrat_friendly &&
  context.beneficiary has vrat_until && context.today <= context.beneficiary.vrat_until
};

@id("caffeine-cap")
@reason("This order has more caffeine than {for} is allowed ({caffeine_cap} mg).")
@hinglish("Is order mein {for} ki caffeine limit ({caffeine_cap} mg) se zyada caffeine hai.")
forbid (principal, action == Action::"purchase_item", resource)
when {
  resource.caffeine_mg > 0 && context.beneficiary has max_caffeine_mg &&
  context.order_caffeine_mg > context.beneficiary.max_caffeine_mg
};

@id("teen-caffeine-cap")
@reason("Teens get at most 100 mg of caffeine per order (about one cola or coffee).")
@hinglish("Bachchon ke ek order mein 100 mg se zyada caffeine nahi (ek cold drink ya coffee jitna).")
forbid (principal, action == Action::"purchase_item", resource)
when {
  resource.caffeine_mg > 0 && context.beneficiary.role == "teen" &&
  !(context.beneficiary has max_caffeine_mg) && context.order_caffeine_mg > 100
}
unless { resource.category == "energy_drinks" }; // already forbidden for teens with a clearer reason
