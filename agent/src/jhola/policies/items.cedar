// ---------- Line-item policies (Action::"purchase_item") ----------

@id("adult-any-category")
@reason("Admins and adults can buy from any category.")
@hinglish("Bade log kuch bhi order kar sakte hain.")
permit (principal, action == Action::"purchase_item", resource)
when { principal.role == "admin" || principal.role == "adult" };

@id("house-help-category-scope")
@reason("House help can order staples, dairy, vegetables, fruits and cleaning items.")
@hinglish("Didi ration, doodh, sabzi, phal aur safai ka saamaan order kar sakti hain.")
permit (principal, action == Action::"purchase_item", resource)
when {
  principal.role == "house_help" &&
  ["staples", "dairy", "vegetables", "fruits", "cleaning"].contains(resource.category)
};

@id("house-help-outside-scope")
@reason("House help cannot order items outside staples, dairy, vegetables, fruits and cleaning.")
@hinglish("Yeh item Didi ki list mein allowed nahi hai.")
forbid (principal, action == Action::"purchase_item", resource)
when {
  principal.role == "house_help" &&
  !["staples", "dairy", "vegetables", "fruits", "cleaning"].contains(resource.category)
};

@id("teen-category-scope")
@reason("Teens can order stationery and snacks.")
@hinglish("Bachche stationery aur snacks order kar sakte hain.")
permit (principal, action == Action::"purchase_item", resource)
when {
  principal.role == "teen" &&
  ["stationery", "snacks"].contains(resource.category)
};

@id("teen-outside-scope")
@reason("Teens can only order stationery and snacks.")
@hinglish("Bachchon ke liye sirf stationery aur snacks allowed hain.")
forbid (principal, action == Action::"purchase_item", resource)
when {
  principal.role == "teen" &&
  !["stationery", "snacks", "energy_drinks"].contains(resource.category)
};

@id("teen-no-energy-drinks")
@reason("Energy drinks are not allowed for teens.")
@hinglish("Energy drink bachchon ke liye mana hai.")
forbid (principal, action == Action::"purchase_item", resource)
when { principal.role == "teen" && resource.category == "energy_drinks" };

@id("min-seller-rating")
@reason("Seller rating is below 4.0.")
@hinglish("Is seller ki rating 4.0 se kam hai.")
forbid (principal, action == Action::"purchase_item", resource)
when { resource.seller_rating.lessThan(decimal("4.0")) };

@id("max-qty-per-line")
@reason("More than 5 units of one item needs the admin.")
@hinglish("Ek item ke 5 se zyada units sirf Mom order kar sakti hain.")
forbid (principal, action == Action::"purchase_item", resource)
when { context.quantity > 5 }
unless { principal.role == "admin" };
