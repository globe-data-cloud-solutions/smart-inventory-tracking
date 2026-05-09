import { BrowserMultiFormatReader, NotFoundException } from "@zxing/browser";

// Supported: Code128, Code39, EAN-13, EAN-8, QR Code, DataMatrix
// Target: < 1 second P90 scan recognition on mid-range Android
// HTTPS is required — iOS Safari blocks camera access on HTTP

export class BarcodeScanner {
  private reader = new BrowserMultiFormatReader();
  private stream: MediaStream | null = null;

  async start(
    videoEl: HTMLVideoElement,
    onResult: (code: string) => void
  ): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment" }, // rear camera
    });

    await this.reader.decodeFromStream(
      this.stream,
      videoEl,
      (result, error) => {
        if (result) onResult(result.getText());
        if (error && !(error instanceof NotFoundException)) {
          console.error("[scanner]", error);
        }
      }
    );
  }

  stop(): void {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.reader.reset();
  }
}
