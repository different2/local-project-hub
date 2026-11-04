"""TEMP observer wrapper: real native pixels in addition to MSI runtime proof."""
import argparse
import ctypes
import json
from pathlib import Path
import sys


def painted_dashboard(image):
    rgb = image.convert('RGB')
    # Exact blue of the owned fixture, not a claim about arbitrary application UIs.
    return sum(1 for color in rgb.getdata() if color == (18,54,70)) >= 10000


def finalize_capture(output, status, native_code, *, preexisting=False):
    # An output-directory refusal must not mutate earlier evidence.
    if preexisting or not output.is_dir():
        return native_code or 1
    import smoke_windows_msi as smoke
    report_path = output / 'report.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    report['native_msi_passed'] = report.get('passed') is True and native_code == 0
    report['native_capture'] = status
    report['passed'] = report['native_msi_passed'] and status.get('attempted') is True and status.get('passed') is True
    if not report['passed'] and not report.get('error'):
        report['error'] = 'Native desktop pixel capture failed or was not attempted'
    smoke.checkpoint(output, report)
    with (output/'native-capture.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(status, stream, indent=2)
        stream.write('\n')
    return 0 if report['passed'] else (native_code or 1)


def main():
    if sys.argv[1:] == ['--self-test']:
        from PIL import Image
        assert painted_dashboard(Image.new('RGB',(400,400),(18,54,70)))
        assert not painted_dashboard(Image.new('RGB',(400,400),'black'))
        assert not painted_dashboard(Image.new('RGB',(400,400),'white'))
        print('Native-pixel observer accepts controlled fixture color and rejects blank controls; NOT native execution')
        return 0
    import smoke_windows_msi as smoke
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--output',type=Path,required=True)
    args,_ = parser.parse_known_args()
    preexisting = args.output.exists() or args.output.is_symlink()
    status = {'attempted':False,'passed':False,'scope':'native Windows desktop-pixel capture of the owned Hub; not a mouse gesture'}
    original = smoke.NativeWindows.window
    def window(self,pid):
        result = original(self,pid)
        if result and not status['attempted']:
            status['attempted'] = True
            try:
                from PIL import ImageGrab
                image = ImageGrab.grab(bbox=tuple(result['frame']),all_screens=True)
                path = args.output/'native-window.png'
                image.save(path)
                status.update(pid=pid,hwnd=result['hwnd'],frame=result['frame'],image=str(path),size=list(image.size),
                              passed=painted_dashboard(image))
                if not status['passed']:status['error']='Native capture lacks the actual dashboard fixture color'
            except Exception as exc:
                status['error'] = type(exc).__name__+': '+str(exc)
        return result
    smoke.NativeWindows.window = window
    if sys.platform == 'win32':
        ctypes.windll.user32.SetProcessDPIAware()
    try:
        code = smoke.main()
    finally:
        smoke.NativeWindows.window = original
    verdict = finalize_capture(args.output, status, code, preexisting=preexisting)
    print(json.dumps({'native_capture':status,'native_msi_exit':code}))
    return verdict


if __name__ == '__main__':
    raise SystemExit(main())
