export async function recognizeProductScreenshot(file: File, onProgress?: (progress: number) => void): Promise<string> {
  const { createWorker, OEM } = await import('tesseract.js');
  const worker = await createWorker(['chi_sim', 'eng'], OEM.LSTM_ONLY, {
    workerPath: '/ocr/worker.min.js',
    corePath: '/ocr/core',
    langPath: '/ocr/lang',
    gzip: true,
    logger(message) {
      if (message.status === 'recognizing text' && typeof message.progress === 'number') onProgress?.(message.progress);
    },
  });
  try {
    const result = await worker.recognize(file);
    return result.data.text.trim();
  } finally {
    await worker.terminate();
  }
}
