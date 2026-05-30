// api/sim.js — Proxy LMU telemetry (fixes CORS + mixed content)
export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'GET') return res.status(405).end();

  const { ip } = req.query;
  if (!ip) return res.status(400).json({ error: 'Missing ip' });

  const base = `http://${ip}:5397/rest`;

  try {
    const [sessionRes, standingsRes] = await Promise.all([
      fetch(`${base}/watch/sessionInfo`, { signal: AbortSignal.timeout(4000) }),
      fetch(`${base}/watch/standings`,   { signal: AbortSignal.timeout(4000) }),
    ]);

    if (!sessionRes.ok) return res.status(502).json({ error: 'LMU not responding' });

    const session  = await sessionRes.json();
    const standings = standingsRes.ok ? await standingsRes.json() : null;

    const p  = standings?.entries?.find(e => e.isPlayer) || {};
    const fc = p.fuelCapacity  || 100;
    const fl = p.fuelLeft      ?? fc;
    const tw = p.frontLeftWear ?? 100;

    return res.status(200).json({
      ok: true,
      position:     p.position       || 1,
      totalEntries: standings?.entries?.length || 1,
      fuelPercent:  (fl / fc) * 100,
      fuelLevel:    parseFloat(fl.toFixed(1)),
      tyreCondition: tw > 70 ? 'OK' : tw > 40 ? 'WARN' : 'CRIT',
      tyreWear:     parseFloat(tw.toFixed(1)),
      gapAhead:     parseFloat((p.timeBehindNext || 0).toFixed(2)),
      lap:          p.lapsCompleted  || 0,
      totalLaps:    session?.maximumLaps || 0,
      weather:      (session?.darkCloud || 0) > 0.5 ? 'Rain' : 'Dry',
      sessionType:  session?.session  || 'Race',
      trackName:    session?.trackName || '',
      carName:      p.vehicleName    || '',
    });

  } catch (e) {
    const msg = e.name === 'TimeoutError'
      ? 'Connection timeout — check IP and LMU is running'
      : e.message;
    return res.status(502).json({ error: msg });
  }
}
