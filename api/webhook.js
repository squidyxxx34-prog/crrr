// api/webhook.js
const Stripe = require('stripe');
const { createClient } = require('@supabase/supabase-js');

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY);
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).end();

  let event;
  try {
    event = stripe.webhooks.constructEvent(
      req.body,
      req.headers['stripe-signature'],
      process.env.STRIPE_WEBHOOK_SECRET
    );
  } catch (err) {
    return res.status(400).json({ error: 'Invalid signature' });
  }

  const userId = event.data.object.metadata?.supabase_user_id;

  switch (event.type) {
    case 'checkout.session.completed':
      await updateStatus(userId, 'active');
      break;
    case 'customer.subscription.deleted':
      await updateStatus(userId, 'cancelled');
      break;
    case 'invoice.payment_failed':
      await updateStatus(userId, 'past_due');
      break;
  }

  res.status(200).json({ received: true });
};

async function updateStatus(userId, status) {
  if (!userId) return;
  await supabase
    .from('users')
    .update({ subscription_status: status })
    .eq('id', userId);
}
