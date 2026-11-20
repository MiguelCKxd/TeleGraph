package org.tgas.qr;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import com.google.zxing.BinaryBitmap;
import com.google.zxing.DecodeHintType;
import com.google.zxing.LuminanceSource;
import com.google.zxing.ReaderException;
import com.google.zxing.RGBLuminanceSource;
import com.google.zxing.common.HybridBinarizer;
import com.google.zxing.qrcode.QRCodeReader;
import com.journeyapps.barcodescanner.CaptureActivity;
import java.util.Collections;
import java.util.Map;

/** The camera and gallery use the same bundled, offline QR decoder. */
public final class QrCaptureActivity extends CaptureActivity {
    public static String readImage(String path) {
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(path, options);
        if (options.outWidth <= 0 || options.outHeight <= 0) return null;
        options.inSampleSize = 1;
        while (Math.max(options.outWidth, options.outHeight) / options.inSampleSize > 2048) {
            options.inSampleSize *= 2;
        }
        options.inJustDecodeBounds = false;
        Bitmap bitmap = BitmapFactory.decodeFile(path, options);
        if (bitmap == null) return null;
        int width = bitmap.getWidth();
        int height = bitmap.getHeight();
        int[] pixels = new int[width * height];
        try {
            bitmap.getPixels(pixels, 0, width, 0, 0, width, height);
        } finally {
            bitmap.recycle();
        }
        LuminanceSource source = new RGBLuminanceSource(width, height, pixels);
        Map<DecodeHintType, ?> hints = Collections.singletonMap(DecodeHintType.TRY_HARDER, true);
        QRCodeReader reader = new QRCodeReader();
        for (LuminanceSource luminance : new LuminanceSource[] {source, source.invert()}) {
            try {
                return reader.decode(new BinaryBitmap(new HybridBinarizer(luminance)), hints).getText();
            } catch (ReaderException unreadable) {
                reader.reset();
            }
        }
        return null;
    }
}
