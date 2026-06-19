import { NextResponse } from 'next/server';
import { getLocalizedText } from '@/lib/translator';

export async function POST(req: Request) {
  const { text, lang } = await req.json();
  const localized = await getLocalizedText(text, lang);
  return NextResponse.json(localized);
}
