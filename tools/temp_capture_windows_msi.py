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
    code = smoke.main()
    if args.output.is_dir():
        (args.output/'native-capture.json').write_text(json.dumps(status,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'native_capture':status,'native_msi_exit':code}))
    return code if code else (0 if status['passed'] else 1)


if __name__ == '__main__':
    raise SystemExit(main())
