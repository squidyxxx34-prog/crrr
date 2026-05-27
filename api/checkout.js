const { userId, plan } = req.body;

const priceId = plan === 'pro' 
  ? process.env.STRIPE_PRICE_ID_2 
  : process.env.STRIPE_PRICE_ID_1;

const session = await stripe.checkout.sessions.create({
  mode: 'subscription',
  line_items: [{ price: priceId, quantity: 1 }],
  metadata: { supabase_user_id: userId },
  // ...
});
