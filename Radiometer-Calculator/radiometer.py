"""
Radiometer Calculator
======================

מחשבון השטף הפוטוני (Photon Flux) הנפלט מסנטימטר מרובע אחד של חומר
הנמצא בטמפרטורה T, בתוך תחום אורכי גל נתון [lambda_1, lambda_2].

הנחות:
    * החומר מתנהג כגוף שחור עם כושר פליטה (emissivity) epsilon = 1.
    * הפליטה היא לחצי כדור (hemispherical), כלומר אנו משתמשים
      בעקומת הפליטה הספקטרלית של פלאנק כשהיא כבר אינטגרלית על כל הזוויות
      (מקדם pi כלול).

פיזיקה
------
חוק פלאנק עבור עוצמת הפליטה הספקטרלית (הספק ליחידת שטח ליחידת אורך גל):

    M_lambda(lambda, T) = (2*pi*h*c**2 / lambda**5) * 1 / (exp(h*c / (lambda*k*T)) - 1)
                          [W / m^2 / m]

האנרגיה של פוטון בודד באורך גל lambda היא:

    E_photon = h*c / lambda

לכן השטף הפוטוני הספקטרלי (מספר פוטונים לשנייה ליחידת שטח ליחידת אורך גל):

    N_lambda(lambda, T) = M_lambda / E_photon
                        = (2*pi*c / lambda**4) * 1 / (exp(h*c / (lambda*k*T)) - 1)
                          [photons / s / m^2 / m]

השטף הפוטוני הכולל בתחום [lambda_1, lambda_2]:

    Phi = integral_{lambda_1}^{lambda_2} N_lambda(lambda, T) d(lambda)
          [photons / s / m^2]

ולבסוף ממירים לסנטימטר מרובע (1 m^2 = 1e4 cm^2).
"""

import math

# ---------------------------------------------------------------------------
# קבועי טבע (SI)
# ---------------------------------------------------------------------------
H = 6.62607015e-34   # קבוע פלאנק            [J*s]
C = 2.99792458e8     # מהירות האור בריק       [m/s]
K_B = 1.380649e-23   # קבוע בולצמן            [J/K]


def photon_spectral_exitance(wavelength_m, temperature_k):
    """
    מחזיר את השטף הפוטוני הספקטרלי N_lambda
    ביחידות photons / s / m^2 / m, עבור אורך גל וטמפרטורה נתונים.
    """
    exponent = (H * C) / (wavelength_m * K_B * temperature_k)

    # הגנה מפני overflow כשהמעריך גדול מאוד (פוטונים קצרי גל / טמפרטורה נמוכה)
    if exponent > 700:
        return 0.0

    return (2.0 * math.pi * C) / (wavelength_m ** 4) / (math.exp(exponent) - 1.0)


def photon_flux(temperature_k, lambda_start_m, lambda_end_m, num_intervals=10000):
    """
    מחשב את השטף הפוטוני הכולל הנפלט מסנטימטר מרובע אחד,
    בתחום אורכי הגל [lambda_start_m, lambda_end_m], בטמפרטורה נתונה.

    האינטגרציה מתבצעת בשיטת סימפסון (Simpson's rule).

    פרמטרים
    --------
    temperature_k : float   - טמפרטורה בקלווין
    lambda_start_m : float  - אורך גל התחלתי במטרים
    lambda_end_m : float    - אורך גל סופי במטרים
    num_intervals : int     - מספר תת-קטעים לאינטגרציה (זוגי)

    מחזיר
    ------
    float - השטף הפוטוני ביחידות photons / s / cm^2
    """
    if temperature_k <= 0:
        raise ValueError("הטמפרטורה חייבת להיות גדולה מאפס (בקלווין).")
    if lambda_start_m <= 0 or lambda_end_m <= 0:
        raise ValueError("אורכי הגל חייבים להיות גדולים מאפס.")
    if lambda_end_m <= lambda_start_m:
        raise ValueError("אורך הגל הסופי חייב להיות גדול מאורך הגל ההתחלתי.")

    # מבטיחים מספר תת-קטעים זוגי עבור שיטת סימפסון
    if num_intervals % 2 == 1:
        num_intervals += 1

    h_step = (lambda_end_m - lambda_start_m) / num_intervals

    total = (photon_spectral_exitance(lambda_start_m, temperature_k)
             + photon_spectral_exitance(lambda_end_m, temperature_k))

    for i in range(1, num_intervals):
        x = lambda_start_m + i * h_step
        weight = 4.0 if i % 2 == 1 else 2.0
        total += weight * photon_spectral_exitance(x, temperature_k)

    # התוצאה ב- photons / s / m^2
    flux_per_m2 = total * h_step / 3.0

    # המרה ל- photons / s / cm^2  (1 m^2 = 1e4 cm^2)
    return flux_per_m2 / 1.0e4


def _prompt_float(message, validate=None):
    """קורא מספר מהמשתמש עם בדיקת תקינות וחזרה על השאלה במקרה של שגיאה."""
    while True:
        try:
            value = float(input(message).strip())
        except ValueError:
            print("  קלט לא תקין - יש להזין מספר.")
            continue
        if validate is not None:
            error = validate(value)
            if error:
                print(f"  {error}")
                continue
        return value


def main():
    print("=" * 55)
    print("        מחשבון רדיומטר - שטף פוטוני (Photon Flux)")
    print("=" * 55)
    print("מחשב את מספר הפוטונים לשנייה הנפלטים מ-1 cm^2 של חומר")
    print("(כושר פליטה epsilon = 1) בתחום אורכי גל נתון.\n")

    temperature = _prompt_float(
        "הזן טמפרטורה [קלווין]: ",
        validate=lambda v: "הטמפרטורה חייבת להיות חיובית." if v <= 0 else None,
    )

    print("\nהזן את תחום אורכי הגל ביחידות ננומטר (nm):")
    lambda_start_nm = _prompt_float(
        "  אורך גל התחלתי [nm]: ",
        validate=lambda v: "אורך הגל חייב להיות חיובי." if v <= 0 else None,
    )
    lambda_end_nm = _prompt_float(
        "  אורך גל סופי [nm]: ",
        validate=lambda v: "אורך הגל חייב להיות חיובי." if v <= 0 else None,
    )

    if lambda_end_nm <= lambda_start_nm:
        lambda_start_nm, lambda_end_nm = lambda_end_nm, lambda_start_nm

    # המרה מננומטר למטר
    lambda_start_m = lambda_start_nm * 1.0e-9
    lambda_end_m = lambda_end_nm * 1.0e-9

    flux = photon_flux(temperature, lambda_start_m, lambda_end_m)

    print("\n" + "-" * 55)
    print("תוצאה:")
    print(f"  טמפרטורה:        {temperature:g} K")
    print(f"  תחום אורכי גל:   {lambda_start_nm:g} - {lambda_end_nm:g} nm")
    print(f"  שטף פוטוני:      {flux:.6e} photons / s / cm^2")
    print("-" * 55)


if __name__ == "__main__":
    main()
