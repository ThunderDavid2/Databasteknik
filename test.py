import pickle
import shelve
import pygame


pygame.init()
screen = pygame.display.set_mode((400, 300))

klädbild = pygame.image.load("Modern_pixel_clothes_FREE.png").convert_alpha()
karaktärsbild = pygame.image.load("TownsPeople2_Trainers.png").convert_alpha()


#Outerwear panelen
x_start = 8
y_start = 36
pitch = 32  #avstånd mellan varje ikons start (16pix ikon + 16pix avstånd)
ikon_storlek = 16

karaktärs_pitch = 64
karaktärs_storlek = 64

#ex röd jacka --> hämta_sprite(bild, 1, 0)
# --> hämta_sprite(bild, 0, 0)
#--> hämta_sprite(bild 4, 1)
# --> hämta_sprite(bild, 6, 0)
def hämta_sprite(bild, x, y, bredd, höjd):
    yta = bild.subsurface(pygame.Rect(x, y, bredd, höjd))
    screen.blit(yta, (0,0))
    return yta

def hämta_klädbild(kolumn, rad):
    x = x_start + kolumn * pitch
    y = y_start + rad * pitch
    return hämta_sprite(klädbild, x, y, ikon_storlek, ikon_storlek)


def hämta_karaktärsbild(kolumn, rad):
    x = kolumn * karaktärs_pitch
    y = rad * karaktärs_pitch
    return hämta_sprite(karaktärsbild, x, y, karaktärs_storlek, karaktärs_storlek)


karaktärs_lista =  [(kolumn, rad) for rad in range(4) for kolumn in range(4)]

plagg_koordinater = {
    "Tröja": (0,0),
    "T-shirt": (4,1),
    "Linne": (6,0),
    "Väst": (1,0),
    "Byxor": (4,0),
    "Shorts": (8,0),
    "Kjol": (4,12),
    "Leggings": (12,0),
    "Hatt": (21,0),
    "Keps": (5,14),
    "Mössa": (45,4),
    "Basker": (3,30),
}


def bygg_karaktär(kolumn, rad, plagg_array, position=(16, 15), skala=(32, 32)):
    bas = hämta_karaktärsbild(kolumn, rad).copy()

    for plagg_namn in plagg_array:
        pk, pr = plagg_koordinater[plagg_namn]
        plagg_sprite = hämta_klädbild(pk, pr)
        skalat = pygame.transform.scale(plagg_sprite, skala)
        bas.blit(skalat, position)
    return bas

överdelar_array = ("Tröja", "T-shirt", "Linne", "Väst")
underdelar_array = ("Byxor", "Shorts", "Kjol", "Leggings")
huvudbonad_array = ("Hatt", "Keps", "Mössa", "Basker")


def välj_plagg(kategori, plagg_array):
    print(f"Välj {kategori}")
    for i, plagg in enumerate(plagg_array, start=1):
        print(i, "-", plagg)
    val = int(input("Ange nummer 1-4: "))
    return plagg_array[val-1]

def välj_karaktär():
    print("Välj din karaktär:")
    for i, (kolumn, rad) in enumerate(karaktärs_lista, start=1):
        print(i, "- Karaktär", i)
    val = int(input("Ange ett nummber 1-16: "))
    return karaktärs_lista[val-1]


användare = input()


def skapa_nytt_konto():
    global användare

    #för skapa nytt konto
    with shelve.open("användare") as db:
        while användare in db:
            print("Användarnamnet är redan taget - ändra namn: ")
            användare = input("Skriv ett nytt användarnamn: ")
        db[användare]=hash(användare)

        vald_kolumn, vald_rad = välj_karaktär()


    #välja sina kläder
    print("Nu ska du välja kläder, du får bara välja en av varje sort.")
    vald_överdel = välj_plagg("överdel", överdelar_array)
    vald_underdel = välj_plagg("underdel", underdelar_array)
    vald_huvudbonad = välj_plagg("huvudbonad", huvudbonad_array)

    with shelve.open("karaktärsdata") as db:
        db[användare] = {
            "Kropp": (vald_kolumn, vald_rad),
            "Kläder": [vald_överdel, vald_underdel, vald_huvudbonad]
        }


    min_karaktär_bild = bygg_karaktär(vald_kolumn, vald_rad, [vald_överdel, vald_underdel, vald_huvudbonad])
    print("Konto skapat!")
    return min_karaktär_bild

skapa_nytt_konto()



