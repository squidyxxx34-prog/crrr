// api/checkout.js
const Stripe = require('stripe');

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY);

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).end();

  const { userId, plan } = req.body;
  if (!userId) return res.status(400).json({ error: 'Missing userId' });

  const priceId = plan === 'pro'
  ? process.env.STRIPE_PRICE_ID_1
  : process.env.STRIPE_PRICE_ID_2;

  if (!priceId) return res.status(400).json({ error: 'Invalid plan' });

  try {
    const session = await stripe.checkout.sessions.create({
      mode: 'subscription',
      line_items: [{ price: priceId, quantity: 1 }],
      metadata: { supabase_user_id: userId },
      success_url: `${process.env.APP_URL}?success=true`,
      cancel_url: `${process.env.APP_URL}?cancelled=true`,
    });

    res.status(200).json({ url: session.url });
  } catch (err) {
    console.error('Checkout error:', err);
    res.status(500).json({ error: 'Internal error' });
  }
};
