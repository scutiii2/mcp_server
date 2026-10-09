// Lazy pdf.js thumbnails. The library and its worker load on first use; each
// document is fetched once; at most MAX_ACTIVE pages render at the same time.
import type { PDFDocumentProxy } from 'pdfjs-dist'

type PdfJs = typeof import('pdfjs-dist')

const MAX_ACTIVE = 2
let library: Promise<PdfJs> | null = null
const documents = new Map<string, Promise<PDFDocumentProxy>>()
let active = 0
const waiting: Array<() => void> = []

function loadLibrary(): Promise<PdfJs> {
  library ??= Promise.all([import('pdfjs-dist'), import('pdfjs-dist/build/pdf.worker.min.mjs?url')]).then(
    ([pdfjs, worker]) => {
      pdfjs.GlobalWorkerOptions.workerSrc = worker.default
      return pdfjs
    },
  )
  return library
}

function loadDocument(url: string): Promise<PDFDocumentProxy> {
  let document = documents.get(url)
  if (!document) {
    document = loadLibrary().then((pdfjs) => pdfjs.getDocument({ url }).promise)
    documents.set(url, document)
    document.catch(() => documents.delete(url))
  }
  return document
}

async function withSlot<T>(work: () => Promise<T>): Promise<T> {
  // A freed slot is handed straight to the next waiter (active stays counted),
  // so a new caller can never slip in between release and wake-up.
  if (active >= MAX_ACTIVE) await new Promise<void>((resolve) => waiting.push(resolve))
  else active++
  try {
    return await work()
  } finally {
    const next = waiting.shift()
    if (next) next()
    else active--
  }
}

/** Draw one page (0-based) into `canvas`, `cssWidth` CSS pixels wide, sharp on HiDPI screens. */
export function renderPage(url: string, pageIndex: number, canvas: HTMLCanvasElement, cssWidth: number): Promise<void> {
  return withSlot(async () => {
    const document = await loadDocument(url)
    const page = await document.getPage(pageIndex + 1)
    const base = page.getViewport({ scale: 1 })
    const viewport = page.getViewport({ scale: (cssWidth * window.devicePixelRatio) / base.width })
    canvas.width = Math.round(viewport.width)
    canvas.height = Math.round(viewport.height)
    try {
      await page.render({ canvas, viewport }).promise
    } finally {
      page.cleanup()
    }
  })
}

/** Drop a cached document, e.g. after its file is removed. */
export function forgetDocument(url: string): void {
  void documents.get(url)?.then((document) => document.destroy()).catch(() => {})
  documents.delete(url)
}
