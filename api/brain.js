// api/brain.js — Vercel serverless function
// Receives race context, calls Groq LLM, returns engineer message

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { system, prompt, isQuestion } = req.body;

  if (!prompt) {
    return res.status(400).json({ error: 'Missing prompt' });
  }

  const apiKey = process.env.GROQ_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ error: 'GROQ_API_KEY not configured' });
  }

  try {
    const response = await fetch('https://api.groq.com/openai/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: 'llama-3.3-70b-versatile',
        max_tokens: 80,
        temperature: 0.7,
        messages: [
          { role: 'system', content: system },
          { role: 'user', content: prompt },
        ],
      }),
    });

    if (!response.ok) {
      const err = await response.text();
      console.error('Groq error:', err);
      return res.status(502).json({ error: 'AI service error' });
    }

    const data = await response.json();
    const message = data.choices?.[0]?.message?.content?.trim() || 'SILENT';

    return res.status(200).json({ message });
  } catch (err) {
    console.error('Brain error:', err);
    return res.status(500).json({ error: 'Internal error' });
  }
}
